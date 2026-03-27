import cv2
import numpy as np
import mss
import win32gui
import win32con
import win32api
import json
import os
import sys
import time
import logging
import threading
import queue
from collections import deque
from datetime import datetime

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
CONFIG_FILE = 'overlay_config.json'

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# Cores (B, G, R)
COLOR_TRANSPARENT  = (0, 0, 0)
COLOR_OK           = (0, 255, 0)
COLOR_UI_TEXT      = (255, 255, 255)
COLOR_UI_BORDER    = (200, 200, 200)
COLOR_ALARM_DOT    = (0, 0, 255)


# ---------------------------------------------------------------------------
# FlowAnalyzer — Optical Flow em thread separada
# ---------------------------------------------------------------------------
class FlowAnalyzer:
    """
    Calcula Optical Flow Farneback dentro da zona a cada frame.
    Mantém média móvel da magnitude e sinaliza alarme quando a velocidade
    média sustentada ultrapassa o limiar configurado.

    Roda em thread daemon para não bloquear o loop do overlay.
    Frames chegam via fila; resultado mais recente em latest_result.

    Calibração baseada nos vídeos de produção:
      - Fluxo normal (vidro estático): ~0.31 px/frame
      - Evento de deriva (vidro se movendo): picos ~1.13 px/frame
      - Padrão default 0.60 = ~2x a média normal => boa margem
    """

    def __init__(self, zone_id, flow_threshold=0.60, window_frames=15):
        self.zone_id        = zone_id
        self.flow_threshold = flow_threshold
        self.window_frames  = window_frames

        self._flow_history  = deque(maxlen=window_frames)
        self._prev_roi      = None
        self._frame_queue   = queue.Queue(maxsize=2)
        self._running       = False
        self._thread        = None

        self.latest_result  = {
            'flow_mean':      0.0,
            'flow_rolling':   0.0,
            'is_motion_alarm': False,
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def submit_frame(self, roi_gray):
        if not self._running:
            return
        try:
            self._frame_queue.put_nowait(roi_gray)
        except queue.Full:
            pass

    def reset(self):
        self._flow_history.clear()
        self._prev_roi = None
        self.latest_result = {
            'flow_mean': 0.0, 'flow_rolling': 0.0, 'is_motion_alarm': False
        }

    def _worker(self):
        while self._running:
            try:
                roi = self._frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if self._prev_roi is None or self._prev_roi.shape != roi.shape:
                self._prev_roi = roi
                continue

            try:
                flow = cv2.calcOpticalFlowFarneback(
                    self._prev_roi, roi, None,
                    pyr_scale=0.5, levels=2, winsize=13,
                    iterations=2, poly_n=5, poly_sigma=1.1, flags=0)
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                mean_mag = float(np.mean(mag))
            except Exception:
                mean_mag = 0.0

            self._prev_roi = roi
            self._flow_history.append(mean_mag)

            rolling   = float(np.mean(self._flow_history)) if self._flow_history else 0.0
            min_count = max(3, self.window_frames // 3)
            is_alarm  = rolling >= self.flow_threshold and len(self._flow_history) >= min_count

            self.latest_result = {
                'flow_mean':       mean_mag,
                'flow_rolling':    rolling,
                'is_motion_alarm': is_alarm,
            }


# ---------------------------------------------------------------------------
# ZoneMonitor
# ---------------------------------------------------------------------------
class ZoneMonitor:
    def __init__(self, polygon=None, sensitivity=50, alarm_limit=500,
                 zone_id=None, flow_threshold=60):
        self.polygon     = polygon if polygon else []
        self.sensitivity = sensitivity
        self.alarm_limit = alarm_limit
        self.zone_id     = zone_id

        self.current_score     = 0
        self.is_alarm          = False
        self.alarm_latched     = False
        self.max_display_score = 5000

        self.invert_logic     = False
        self.alarm_delay_ms   = 0
        self.first_alarm_time = None
        self.edge_method      = 'SOBEL'

        # flow_threshold armazenado como inteiro (60 = 0.60 px/frame)
        self.flow_threshold = flow_threshold
        self.flow_enabled   = True
        self._flow_analyzer = FlowAnalyzer(
            zone_id=zone_id,
            flow_threshold=flow_threshold / 100.0,
            window_frames=15)
        self._flow_analyzer.start()

        self.logger              = None
        self.last_log_time       = 0
        self.log_interval        = 1.0

        self._snapshot_dir         = None
        self._last_snapshot_time   = 0
        self._snapshot_interval    = 5.0

    def setup_logger(self, log_dir):
        if self.zone_id is None:
            return
        self._snapshot_dir = os.path.join(log_dir, 'snapshots')
        os.makedirs(self._snapshot_dir, exist_ok=True)

        name = f"zone_{self.zone_id}"
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            log_file = os.path.join(log_dir, f"area_{self.zone_id}_log.txt")
            h = logging.FileHandler(log_file, encoding='utf-8')
            h.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
            self.logger.addHandler(h)

    def set_flow_threshold(self, value_int):
        self.flow_threshold = value_int
        self._flow_analyzer.flow_threshold = value_int / 100.0

    def to_dict(self):
        return {
            "polygon":        self.polygon,
            "sensitivity":    self.sensitivity,
            "alarm_limit":    self.alarm_limit,
            "zone_id":        self.zone_id,
            "invert_logic":   self.invert_logic,
            "alarm_delay_ms": self.alarm_delay_ms,
            "edge_method":    self.edge_method,
            "flow_threshold": self.flow_threshold,
            "flow_enabled":   self.flow_enabled,
        }

    @classmethod
    def from_dict(cls, data):
        zone = cls(
            polygon=data.get("polygon"),
            sensitivity=data.get("sensitivity", 50),
            alarm_limit=data.get("alarm_limit", 500),
            zone_id=data.get("zone_id"),
            flow_threshold=data.get("flow_threshold", 60),
        )
        zone.invert_logic   = data.get("invert_logic", False)
        zone.alarm_delay_ms = data.get("alarm_delay_ms", 0)
        zone.edge_method    = data.get("edge_method", 'SOBEL')
        zone.flow_enabled   = data.get("flow_enabled", True)
        zone._flow_analyzer.flow_threshold = zone.flow_threshold / 100.0
        return zone

    def process(self, frame_gray, frame_bgr, width, height):
        if len(self.polygon) < 3:
            return 0, False

        # Máscara poligonal
        mask = np.zeros((height, width), dtype=np.uint8)
        pts  = np.array([self.polygon], dtype=np.int32)
        cv2.fillPoly(mask, pts, 255)
        roi_gray = cv2.bitwise_and(frame_gray, frame_gray, mask=mask)

        # Bounding box para recorte eficiente
        x_coords = [p[0] for p in self.polygon]
        y_coords = [p[1] for p in self.polygon]
        bx1 = max(0, min(x_coords)); bx2 = min(width,  max(x_coords))
        by1 = max(0, min(y_coords)); by2 = min(height, max(y_coords))
        roi_crop = frame_gray[by1:by2, bx1:bx2]

        # Envia para Optical Flow
        if self.flow_enabled and roi_crop.size > 0:
            self._flow_analyzer.submit_frame(roi_crop.copy())

        # Detecção de borda (Sobel ou Canny)
        if self.edge_method == 'CANNY':
            self.edges_binary = cv2.Canny(roi_gray, self.sensitivity, self.sensitivity * 2)
        else:
            blur      = cv2.GaussianBlur(roi_gray, (5, 5), 0)
            sobelx    = cv2.Sobel(blur, cv2.CV_64F, 1, 0, ksize=3)
            sobel_abs = cv2.convertScaleAbs(sobelx)
            _, self.edges_binary = cv2.threshold(sobel_abs, self.sensitivity, 255, cv2.THRESH_BINARY)

        self.current_score = cv2.countNonZero(self.edges_binary)

        # Condição Sobel
        if self.invert_logic:
            sobel_cond = self.current_score > self.alarm_limit
        else:
            sobel_cond = self.current_score < self.alarm_limit

        # Condição Flow
        flow_result = self._flow_analyzer.latest_result
        flow_alarm  = flow_result['is_motion_alarm'] if self.flow_enabled else False

        # Alarme se qualquer um disparar
        condition_met = sobel_cond or flow_alarm

        self.is_alarm = False
        if condition_met:
            if self.alarm_delay_ms > 0:
                if self.first_alarm_time is None:
                    self.first_alarm_time = time.time()
                if (time.time() - self.first_alarm_time) * 1000 >= self.alarm_delay_ms:
                    self.is_alarm = True
            else:
                self.is_alarm = True
        else:
            self.first_alarm_time = None

        if self.is_alarm:
            self.alarm_latched = True
            self._do_alarm_actions(frame_bgr, flow_result)

        return self.current_score, self.is_alarm

    def _do_alarm_actions(self, frame_bgr, flow_result):
        now     = time.time()
        rolling = flow_result.get('flow_rolling', 0.0)
        inst    = flow_result.get('flow_mean', 0.0)

        if self.logger and (now - self.last_log_time >= self.log_interval):
            self.logger.info(
                f"ALARM | Sobel={self.current_score} | SobelLimit={self.alarm_limit} | "
                f"Flow_avg={rolling:.3f}px/f | Flow_inst={inst:.3f}px/f | "
                f"FlowThresh={self.flow_threshold/100.0:.2f}px/f"
            )
            self.last_log_time = now

        if self._snapshot_dir and (now - self._last_snapshot_time >= self._snapshot_interval):
            try:
                ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = f"zona{self.zone_id}_{ts}_flow{rolling:.2f}.jpg"
                path  = os.path.join(self._snapshot_dir, fname)

                x_coords = [p[0] for p in self.polygon]
                y_coords = [p[1] for p in self.polygon]
                bx1 = max(0, min(x_coords)); bx2 = max(x_coords)
                by1 = max(0, min(y_coords)); by2 = max(y_coords)
                crop = frame_bgr[by1:by2, bx1:bx2]

                if crop.size > 0:
                    snap = crop.copy()
                    cv2.putText(snap,
                        f"Z{self.zone_id} Flow:{rolling:.2f}px/f Sobel:{self.current_score}",
                        (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                    cv2.imwrite(path, snap)
                    self._last_snapshot_time = now
            except Exception as e:
                print(f"Snapshot erro zona {self.zone_id}: {e}")

    def get_centroid(self):
        if len(self.polygon) < 3:
            return None
        pts = np.array(self.polygon, dtype=np.float32)
        return (int(np.mean(pts[:, 0])), int(np.mean(pts[:, 1])))

    def draw(self, image, is_config_mode=False):
        if not is_config_mode:
            if self.alarm_latched and len(self.polygon) >= 3:
                c = self.get_centroid()
                if c:
                    cv2.circle(image, c, 5, COLOR_ALARM_DOT, -1)
            return

        if len(self.polygon) < 3:
            if self.polygon:
                pts = np.array([self.polygon], dtype=np.int32)
                cv2.polylines(image, [pts], False, COLOR_UI_BORDER, 1)
                for pt in self.polygon:
                    cv2.circle(image, tuple(pt), 3, COLOR_UI_BORDER, -1)
            return

        pts = np.array([self.polygon], dtype=np.int32)

        if hasattr(self, 'edges_binary'):
            image[self.edges_binary > 0] = (0, 255, 255)

        cv2.polylines(image, [pts], True, COLOR_OK, 2)

        # Gauge Sobel — barra vertical maior ao lado do primeiro ponto
        x, y = self.polygon[0]
        bw, bh = 22, 120          # largura x altura da barra
        bx = x - bw - 6          # posiciona à esquerda do ponto
        by = y

        # Fundo da barra
        cv2.rectangle(image, (bx, by), (bx+bw, by+bh), (60, 60, 60), -1)
        cv2.rectangle(image, (bx, by), (bx+bw, by+bh), (120, 120, 120), 1)

        # Preenchimento proporcional ao score
        fill_ratio = min(self.current_score / self.max_display_score, 1.0)
        fh = int(fill_ratio * bh)
        bar_color = (0, 80, 255) if self.alarm_latched else COLOR_OK
        if fh > 0:
            cv2.rectangle(image, (bx, by+bh-fh), (bx+bw, by+bh), bar_color, -1)

        # Linha do limite de alarme (amarela espessa)
        lr = min(self.alarm_limit / self.max_display_score, 1.0)
        ly = int(by + bh - lr * bh)
        cv2.line(image, (bx-4, ly), (bx+bw+4, ly), (0, 220, 255), 3)

        # Texto: score atual
        cv2.putText(image, str(self.current_score),
                    (bx, by - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, bar_color, 1)

        # Texto: status OK / ALARM
        status     = "ALARM" if self.alarm_latched else "OK"
        status_col = (0, 80, 255) if self.alarm_latched else COLOR_OK
        cv2.putText(image, status,
                    (bx, by - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_col, 2)

        # Info Flow — abaixo da barra
        fr      = self._flow_analyzer.latest_result
        rolling = fr.get('flow_rolling', 0.0)
        thresh  = self.flow_threshold / 100.0
        fcol    = (0, 80, 255) if fr.get('is_motion_alarm') else (180, 180, 180)
        flabel  = "FLW" if self.flow_enabled else "FLW:OFF"
        cv2.putText(image, f"{flabel} {rolling:.2f}/{thresh:.2f}",
                    (bx, by+bh+18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, fcol, 1)

        if self.alarm_latched:
            c = self.get_centroid()
            if c:
                cv2.circle(image, c, 5, COLOR_ALARM_DOT, -1)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class App:
    def __init__(self):
        self.zones             = []
        self.selected_zone_idx = -1
        self.mode_monitor      = True
        self.drawing_active    = False
        self.running           = True

        self.sct          = mss.mss()
        self.monitor_area = self.sct.monitors[1]
        self.width        = self.monitor_area["width"]
        self.height       = self.monitor_area["height"]

        self.window_name = "OverlayAlarm"
        self.ctrl_window = "Ajustes"

        self.base_path = get_app_path()
        self.log_dir   = os.path.join(self.base_path, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)

        self.load_config()

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN)

        try:
            import ctypes
            hwnd = win32gui.FindWindow(None, self.window_name)
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
            print("Anti-Capture ativado")
        except Exception as e:
            print(f"Aviso Anti-Capture: {e}")

        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        self.current_style_mode = None
        self.input_text         = ""
        self.input_focus        = None

        # Layout botões
        btn_w, btn_h = 100, 40
        mr, sp       = 20, 10

        x_reload            = self.width - mr - btn_w
        self.btn_reload_cfg = (x_reload, 100, btn_w, btn_h)
        x_reset              = x_reload - sp - btn_w
        self.btn_reset_alarm = (x_reset, 100, btn_w, btn_h)
        x_clear              = x_reset - sp - btn_w
        self.btn_clear_cfg   = (x_clear, 100, btn_w, btn_h)
        x_inv               = x_clear - sp - btn_w
        self.btn_inv_logic  = (x_inv, 100, btn_w, btn_h)
        x_delay          = x_inv - sp - btn_w
        self.btn_delay   = (x_delay, 100, btn_w, btn_h)
        x_method          = x_delay - sp - btn_w
        self.btn_method   = (x_method, 100, btn_w, btn_h)
        x_flow                 = x_method - sp - btn_w
        self.btn_flow_toggle   = (x_flow, 100, btn_w, btn_h)

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            self.zones = [ZoneMonitor.from_dict(z) for z in data]
            for i, zone in enumerate(self.zones):
                if zone.zone_id is None:
                    zone.zone_id = i
                zone.setup_logger(self.log_dir)
                zone._flow_analyzer.start()
            self.selected_zone_idx = -1
            print(f"Carregadas {len(self.zones)} zonas.")
        except Exception as e:
            print(f"Erro ao carregar config: {e}")

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump([z.to_dict() for z in self.zones], f, indent=4)
        except Exception as e:
            print(f"Erro ao salvar config: {e}")

    def update_window_style(self, alpha_val=255):
        hwnd = win32gui.FindWindow(None, self.window_name)
        if not hwnd:
            return
        if self.current_style_mode == self.mode_monitor and self.mode_monitor:
            return
        self.current_style_mode = self.mode_monitor
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        base  = style | win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST
        if self.mode_monitor:
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                                   base | win32con.WS_EX_TRANSPARENT)
            win32gui.SetLayeredWindowAttributes(hwnd, 0, 0, win32con.LWA_COLORKEY)
            try: cv2.destroyWindow(self.ctrl_window)
            except: pass
        else:
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                                   base & ~win32con.WS_EX_TRANSPARENT)
            try:
                win32gui.SetLayeredWindowAttributes(hwnd, 0, alpha_val, win32con.LWA_ALPHA)
            except: pass

    def mouse_callback(self, event, x, y, flags, param):
        if self.mode_monitor:
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            if not self.drawing_active:
                def in_btn(btn):
                    bx, by, bw, bh = btn
                    return bx <= x <= bx+bw and by <= y <= by+bh

                if in_btn(self.btn_flow_toggle):
                    if self.selected_zone_idx != -1:
                        z = self.zones[self.selected_zone_idx]
                        z.flow_enabled = not z.flow_enabled
                    return

                if in_btn(self.btn_inv_logic):
                    if self.selected_zone_idx != -1:
                        self.zones[self.selected_zone_idx].invert_logic = \
                            not self.zones[self.selected_zone_idx].invert_logic
                    return

                if in_btn(self.btn_delay):
                    if self.selected_zone_idx != -1:
                        self.input_focus = 'DELAY'
                        self.input_text  = str(
                            self.zones[self.selected_zone_idx].alarm_delay_ms)
                    return

                if in_btn(self.btn_method):
                    if self.selected_zone_idx != -1:
                        z = self.zones[self.selected_zone_idx]
                        z.edge_method = 'CANNY' if z.edge_method == 'SOBEL' else 'SOBEL'
                    return

                self.input_focus = None

                if in_btn(self.btn_reset_alarm):
                    for z in self.zones:
                        z.alarm_latched = False
                        z._flow_analyzer.reset()
                    return

                if in_btn(self.btn_reload_cfg):
                    self.load_config()
                    return

                if in_btn(self.btn_clear_cfg):
                    result = win32api.MessageBox(
                        0,
                        "Tem certeza que deseja apagar TODAS as zonas?\n"
                        "Essa ação não pode ser desfeita.",
                        "Confirmar Exclusão",
                        win32con.MB_YESNO | win32con.MB_ICONWARNING)
                    if result == win32con.IDYES:
                        for z in self.zones:
                            z._flow_analyzer.stop()
                        self.zones = []
                        self.selected_zone_idx = -1
                        self.save_config()
                        self.refresh_trackbars()
                    return

            if self.drawing_active:
                if self.selected_zone_idx != -1:
                    self.zones[self.selected_zone_idx].polygon.append([x, y])
            else:
                new_zone = ZoneMonitor()
                max_id   = max((z.zone_id for z in self.zones
                                if z.zone_id is not None), default=-1)
                new_zone.zone_id = max_id + 1
                new_zone.setup_logger(self.log_dir)
                new_zone._flow_analyzer.start()
                new_zone.polygon.append([x, y])
                self.zones.append(new_zone)
                self.selected_zone_idx = len(self.zones) - 1
                self.drawing_active    = True
                self.refresh_trackbars()

        elif event == cv2.EVENT_RBUTTONDOWN:
            if not self.drawing_active:
                clicked = -1
                for i, zone in enumerate(self.zones):
                    if len(zone.polygon) > 2:
                        poly_np = np.array(zone.polygon, dtype=np.int32)
                        if cv2.pointPolygonTest(poly_np, (x, y), False) >= 0:
                            clicked = i
                            break
                if clicked != -1:
                    self.selected_zone_idx = clicked
                    self.refresh_trackbars()
                else:
                    self.selected_zone_idx = -1
                    try: cv2.destroyWindow(self.ctrl_window)
                    except: pass

    def refresh_trackbars(self):
        if self.selected_zone_idx == -1:
            return

        # Destroi e recria sempre — createTrackbar ignora silenciosamente
        # trackbars duplicados, então a única forma confiável de garantir
        # que todos os sliders apareçam é partir de uma janela limpa.
        try:
            cv2.destroyWindow(self.ctrl_window)
        except Exception:
            pass

        cv2.namedWindow(self.ctrl_window, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.ctrl_window, 420, 220)
        cv2.moveWindow(self.ctrl_window, 20, 200)

        z = self.zones[self.selected_zone_idx]

        def on_sens(val):
            if self.selected_zone_idx != -1:
                self.zones[self.selected_zone_idx].sensitivity = val

        def on_limit(val):
            if self.selected_zone_idx != -1:
                self.zones[self.selected_zone_idx].alarm_limit = val

        def on_flow(val):
            if self.selected_zone_idx != -1:
                self.zones[self.selected_zone_idx].set_flow_threshold(val)

        cv2.createTrackbar("Sensibilidade",  self.ctrl_window,
                           z.sensitivity, 255, on_sens)
        cv2.createTrackbar("Limite Sobel",   self.ctrl_window,
                           z.alarm_limit, 5000, on_limit)
        cv2.createTrackbar("Flow px/f x100", self.ctrl_window,
                           z.flow_threshold, 200, on_flow)

        hwnd_ctrl = win32gui.FindWindow(None, self.ctrl_window)
        if hwnd_ctrl:
            win32gui.SetWindowPos(hwnd_ctrl, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

    def run(self):
        opacity_window = "Opacidade Tela"
        self.edit_opacity = 180

        def on_opacity(val):
            self.edit_opacity = val
            hwnd = win32gui.FindWindow(None, self.window_name)
            if hwnd and not self.mode_monitor:
                win32gui.SetLayeredWindowAttributes(hwnd, 0, self.edit_opacity,
                                                    win32con.LWA_ALPHA)

        while self.running:
            sct_img    = self.sct.grab(self.monitor_area)
            frame_bgr  = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
            frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

            if not self.mode_monitor:
                if cv2.getWindowProperty(opacity_window, cv2.WND_PROP_VISIBLE) < 1:
                    cv2.namedWindow(opacity_window, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(opacity_window, 300, 60)
                    cv2.moveWindow(opacity_window, 20, 20)
                    cv2.createTrackbar("Alpha", opacity_window,
                                       self.edit_opacity, 255, on_opacity)
                    hwnd_op = win32gui.FindWindow(None, opacity_window)
                    if hwnd_op:
                        win32gui.SetWindowPos(hwnd_op, win32con.HWND_TOPMOST,
                                              0, 0, 0, 0,
                                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                self.update_window_style(alpha_val=self.edit_opacity)
            else:
                try: cv2.destroyWindow(opacity_window)
                except: pass
                self.update_window_style()

            for z in self.zones:
                z.process(frame_gray, frame_bgr, self.width, self.height)

            overlay        = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            is_config_mode = not self.mode_monitor

            for z in self.zones:
                z.draw(overlay, is_config_mode=is_config_mode)

            if not self.mode_monitor:
                cv2.rectangle(overlay, (0, 0), (self.width, 150), (30, 30, 30), -1)
                cv2.putText(overlay, "MODO EDICAO (TAB para sair)",
                            (self.width//2 - 130, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                cv2.putText(overlay,
                            "Botao Dir: Selecionar | Ctrl+O: Fechar Zona | Ctrl+J: Sair",
                            (self.width//2 - 300, 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

                def draw_btn(rect, bg, label, border=None):
                    bx, by, bw, bh = rect
                    cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), bg, -1)
                    if border:
                        cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), border, 1)
                    cv2.putText(overlay, label, (bx+6, by+26),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)

                draw_btn(self.btn_reset_alarm, (0, 0, 150),   "RESET ALARM")
                draw_btn(self.btn_reload_cfg,  (0, 150, 150), "RELOAD CFG")
                draw_btn(self.btn_clear_cfg,   (0, 0, 0),     "APAGAR TUDO", (0,0,255))

                z = self.zones[self.selected_zone_idx] \
                    if self.selected_zone_idx != -1 else None

                inv_bg  = (0,0,150) if (z and z.invert_logic) else \
                          ((0,100,0) if z else (50,50,50))
                inv_txt = ("LOGIC:INV" if z.invert_logic else "LOGIC:NRM") \
                          if z else "LOGIC:--"
                draw_btn(self.btn_inv_logic, inv_bg, inv_txt)

                if z:
                    dly_bg  = (200,100,0) if self.input_focus=='DELAY' \
                               else (100,100,100)
                    dly_txt = (self.input_text+"|") if self.input_focus=='DELAY' \
                               else f"DLY:{z.alarm_delay_ms}ms"
                else:
                    dly_bg, dly_txt = (50,50,50), "DELAY:--"
                draw_btn(self.btn_delay, dly_bg, dly_txt)

                mth_bg  = (128,0,128) if (z and z.edge_method=='CANNY') \
                           else ((100,0,0) if z else (50,50,50))
                mth_txt = f"ALG:{z.edge_method}" if z else "ALG:--"
                draw_btn(self.btn_method, mth_bg, mth_txt)

                if z:
                    fl_bg  = (0,140,0) if z.flow_enabled else (60,60,60)
                    fl_val = z._flow_analyzer.latest_result.get('flow_rolling', 0.0)
                    fl_txt = f"FLOW:{fl_val:.2f}" if z.flow_enabled else "FLOW:OFF"
                else:
                    fl_bg, fl_txt = (50,50,50), "FLOW:--"
                draw_btn(self.btn_flow_toggle, fl_bg, fl_txt)

            cv2.imshow(self.window_name, overlay)
            key = cv2.waitKey(1) & 0xFF

            if self.input_focus == 'DELAY':
                if 48 <= key <= 57:
                    self.input_text += chr(key)
                elif key == 8:
                    self.input_text = self.input_text[:-1]
                elif key == 13:
                    if self.selected_zone_idx != -1 and self.input_text.isdigit():
                        self.zones[self.selected_zone_idx].alarm_delay_ms = \
                            int(self.input_text)
                    self.input_focus = None
                elif key == 27:
                    self.input_focus = None
                continue

            if key == 9:
                self.mode_monitor   = not self.mode_monitor
                self.drawing_active = False
                if self.mode_monitor:
                    self.selected_zone_idx = -1

            if key == 15:
                if self.drawing_active:
                    self.drawing_active = False
                    if self.selected_zone_idx != -1 and \
                       len(self.zones[self.selected_zone_idx].polygon) < 3:
                        self.zones[self.selected_zone_idx]._flow_analyzer.stop()
                        self.zones.pop(self.selected_zone_idx)
                        self.selected_zone_idx = -1
                        try: cv2.destroyWindow(self.ctrl_window)
                        except: pass

            if key == 10:
                self.running = False

            if key in (127, 46):
                if not self.mode_monitor and self.selected_zone_idx != -1:
                    self.zones[self.selected_zone_idx]._flow_analyzer.stop()
                    self.zones.pop(self.selected_zone_idx)
                    self.selected_zone_idx = -1
                    self.refresh_trackbars()

        for z in self.zones:
            z._flow_analyzer.stop()
        self.save_config()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    app = App()
    app.run()
