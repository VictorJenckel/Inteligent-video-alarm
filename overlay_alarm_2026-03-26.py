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

# --- Configurações ---
CONFIG_FILE = 'overlay_config.json'

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# Cores (B, G, R)
COLOR_TRANSPARENT = (0, 0, 0)       # Preto Absoluto (Será invisível)
COLOR_OK = (0, 255, 0)              # Verde
COLOR_UI_TEXT = (255, 255, 255)
COLOR_UI_BORDER = (200, 200, 200)
COLOR_ALARM_DOT = (0, 0, 255)       # Vermelho (círculo de alarme)

class ZoneMonitor:
    def __init__(self, polygon=None, sensitivity=50, alarm_limit=500, zone_id=None):
        self.polygon = polygon if polygon else [] # Lista de [x, y]
        self.sensitivity = sensitivity
        self.alarm_limit = alarm_limit
        self.zone_id = zone_id
        
        self.current_score = 0
        self.is_alarm = False
        self.alarm_latched = False
        self.max_display_score = 5000 
        
        self.invert_logic = False
        self.alarm_delay_ms = 0
        self.first_alarm_time = None
        self.edge_method = 'SOBEL'
        
        self.logger = None
        self.last_log_time = 0
        self.log_interval = 1.0 # 1 segundo entre logs

    def setup_logger(self, log_dir):
        if self.zone_id is None:
            return
            
        self.logger_name = f"zone_{self.zone_id}"
        self.logger = logging.getLogger(self.logger_name)
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            log_file = os.path.join(log_dir, f"area_{self.zone_id}_log.txt")
            handler = logging.FileHandler(log_file, encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s | %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler) 

    def to_dict(self):
        return {
            "polygon": self.polygon,
            "sensitivity": self.sensitivity,
            "alarm_limit": self.alarm_limit,
            "zone_id": self.zone_id,
            "invert_logic": self.invert_logic,
            "alarm_delay_ms": self.alarm_delay_ms,
            "edge_method": self.edge_method
        }

    @classmethod
    def from_dict(cls, data):
        zone = cls(
            polygon=data.get("polygon"),
            sensitivity=data.get("sensitivity", 50),
            alarm_limit=data.get("alarm_limit", 500),
            zone_id=data.get("zone_id")
        )
        zone.invert_logic = data.get("invert_logic", False)
        zone.alarm_delay_ms = data.get("alarm_delay_ms", 0)
        zone.edge_method = data.get("edge_method", 'SOBEL')
        return zone

    def process(self, frame_gray, width, height):
        if len(self.polygon) < 3:
            return 0, False

        mask = np.zeros((height, width), dtype=np.uint8)
        pts = np.array([self.polygon], dtype=np.int32)
        cv2.fillPoly(mask, pts, 255)

        roi = cv2.bitwise_and(frame_gray, frame_gray, mask=mask)

        if self.edge_method == 'CANNY':
            self.edges_binary = cv2.Canny(roi, self.sensitivity, self.sensitivity * 2)
        else:
            blur = cv2.GaussianBlur(roi, (5, 5), 0)
            sobelx = cv2.Sobel(blur, cv2.CV_64F, 1, 0, ksize=3) 
            sobel_abs = cv2.convertScaleAbs(sobelx)
            _, self.edges_binary = cv2.threshold(sobel_abs, self.sensitivity, 255, cv2.THRESH_BINARY)
        
        self.current_score = cv2.countNonZero(self.edges_binary)

        if self.invert_logic:
            condition_met = self.current_score > self.alarm_limit
        else:
            condition_met = self.current_score < self.alarm_limit
            
        self.is_alarm = False
        
        if condition_met:
            if self.alarm_delay_ms > 0:
                if self.first_alarm_time is None:
                    self.first_alarm_time = time.time()
                
                elapsed_ms = (time.time() - self.first_alarm_time) * 1000
                if elapsed_ms >= self.alarm_delay_ms:
                    self.is_alarm = True
            else:
                self.is_alarm = True
        else:
            self.first_alarm_time = None
            self.is_alarm = False

        if self.is_alarm:
            self.alarm_latched = True
            
        if self.is_alarm and self.logger:
            current_time = time.time()
            if current_time - self.last_log_time >= self.log_interval:
                self.logger.info(f"ALARM ACTIVE | Score: {self.current_score} | Limit: {self.alarm_limit}")
                self.last_log_time = current_time
        
        return self.current_score, self.is_alarm

    def get_centroid(self):
        """Retorna o centroide do polígono."""
        if len(self.polygon) < 3:
            return None
        pts = np.array(self.polygon, dtype=np.float32)
        cx = int(np.mean(pts[:, 0]))
        cy = int(np.mean(pts[:, 1]))
        return (cx, cy)

    def draw(self, image, is_config_mode=False):
        """
        is_config_mode=True  -> Modo TAB (edição): desenha contorno + UI completa
        is_config_mode=False -> Modo Monitor: só desenha o círculo de alarme se ativo
        """
        # --- MODO MONITOR: apenas círculo de alarme, sem contorno ---
        if not is_config_mode:
            if self.alarm_latched and len(self.polygon) >= 3:
                centroid = self.get_centroid()
                if centroid:
                    cv2.circle(image, centroid, 5, COLOR_ALARM_DOT, -1)  # raio 5 = diâmetro 10px
            return

        # --- MODO CONFIGURAÇÃO (TAB): contorno + UI completa ---
        if len(self.polygon) < 3:
            if len(self.polygon) > 0:
                pts = np.array([self.polygon], dtype=np.int32)
                cv2.polylines(image, [pts], False, COLOR_UI_BORDER, 1)
                for pt in self.polygon:
                    cv2.circle(image, tuple(pt), 3, COLOR_UI_BORDER, -1)
            return

        pts = np.array([self.polygon], dtype=np.int32)

        # Sempre verde no modo configuração (sem vermelho de alarme)
        color = COLOR_OK
        
        thickness = 2
        
        # Desenha as bordas detectadas (Visualização do "Vidro")
        if hasattr(self, 'edges_binary'):
            image[self.edges_binary > 0] = (0, 255, 255)

        cv2.polylines(image, [pts], True, color, thickness)
        
        # Barra de Nível (Gauge) ao lado do primeiro ponto
        x, y = self.polygon[0]
        
        bar_w, bar_h = 10, 50
        bar_x = x - 15
        bar_y = y
        
        cv2.rectangle(image, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), -1)
        
        fill_ratio = min(self.current_score / self.max_display_score, 1.0)
        fill_h = int(fill_ratio * bar_h)
        cv2.rectangle(image, (bar_x, bar_y + bar_h - fill_h), (bar_x + bar_w, bar_y + bar_h), color, -1)
        
        limit_ratio = min(self.alarm_limit / self.max_display_score, 1.0)
        limit_y = int(bar_y + bar_h - (limit_ratio * bar_h))
        cv2.line(image, (bar_x - 2, limit_y), (bar_x + bar_w + 2, limit_y), (0, 255, 255), 2)
        
        status_text = "OK" if not self.alarm_latched else "ALARM"
        cv2.putText(image, f"{self.current_score} | {status_text}", (bar_x, bar_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # Círculo de alarme visível também no modo configuração quando ativo
        if self.alarm_latched:
            centroid = self.get_centroid()
            if centroid:
                cv2.circle(image, centroid, 5, COLOR_ALARM_DOT, -1)


class App:
    def __init__(self):
        self.zones = []
        self.selected_zone_idx = -1
        self.mode_monitor = True 
        self.drawing_active = False 
        self.running = True
        
        self.sct = mss.mss()
        self.monitor_area = self.sct.monitors[1]
        self.width = self.monitor_area["width"]
        self.height = self.monitor_area["height"]
        
        self.window_name = "OverlayAlarm"
        self.ctrl_window = "Ajustes"
        
        self.base_path = get_app_path()
        self.log_dir = os.path.join(self.base_path, 'logs')
        if not os.path.exists(self.log_dir):
            try:
                os.makedirs(self.log_dir)
            except Exception as e:
                print(f"Erro ao criar pasta logs: {e}")

        self.load_config()

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        
        try:
             hwnd = win32gui.FindWindow(None, self.window_name)
             WDA_EXCLUDEFROMCAPTURE = 0x00000011
             import ctypes
             ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
             print("Anti-Capture Mode Ativado (Overlay invisível para mss)")
        except Exception as e:
             print(f"Aviso: Falha ao ativar Anti-Capture: {e}")
        
        cv2.setMouseCallback(self.window_name, self.mouse_callback)
        
        self.current_style_mode = None
        self.input_active_zone = -1
        self.input_text = ""
        self.input_focus = None
        
        btn_w, btn_h = 100, 40
        margin_right = 20
        spacing = 10
        
        x_reload = self.width - margin_right - btn_w
        self.btn_reload_cfg = (x_reload, 100, btn_w, btn_h)
        
        x_reset = x_reload - spacing - btn_w
        self.btn_reset_alarm = (x_reset, 100, btn_w, btn_h)
        
        x_clear = x_reset - spacing - btn_w
        self.btn_clear_cfg = (x_clear, 100, btn_w, btn_h)
        
        x_inv = x_clear - spacing - btn_w
        self.btn_inv_logic = (x_inv, 100, btn_w, btn_h)
        
        x_delay = x_inv - spacing - btn_w
        self.btn_delay = (x_delay, 100, btn_w, btn_h)

        x_method = x_delay - spacing - btn_w
        self.btn_method = (x_method, 100, btn_w, btn_h)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self.zones = [ZoneMonitor.from_dict(z) for z in data]
                    
                max_id = -1
                for i, zone in enumerate(self.zones):
                    if zone.zone_id is None:
                        zone.zone_id = i
                    if zone.zone_id > max_id:
                        max_id = zone.zone_id
                    zone.setup_logger(self.log_dir)

                print(f"Carregadas {len(self.zones)} zonas.")
                self.selected_zone_idx = -1
            except Exception as e:
                print(f"Erro ao carregar config: {e}")

    def save_config(self):
        data = [z.to_dict() for z in self.zones]
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Erro ao salvar config: {e}")

    def update_window_style(self, alpha_val=255):
        hwnd = win32gui.FindWindow(None, self.window_name)
        if not hwnd: return

        if self.current_style_mode == self.mode_monitor and self.mode_monitor:
             return
        
        if self.mode_monitor:
             self.current_style_mode = True
        else:
             self.current_style_mode = False

        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)

        base_style = style | win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST

        if self.mode_monitor:
            new_style = base_style | win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)
            win32gui.SetLayeredWindowAttributes(hwnd, 0, 0, win32con.LWA_COLORKEY)
            
            try: cv2.destroyWindow(self.ctrl_window)
            except: pass
        else:
            new_style = base_style & ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_style)
            
            try:
                win32gui.SetLayeredWindowAttributes(hwnd, 0, alpha_val, win32con.LWA_ALPHA)
            except:
                pass

    def mouse_callback(self, event, x, y, flags, param):
        if self.mode_monitor: return 

        if event == cv2.EVENT_LBUTTONDOWN:
            if not self.drawing_active:
                bx, by, bw, bh = self.btn_inv_logic
                if bx <= x <= bx+bw and by <= y <= by+bh:
                    if self.selected_zone_idx != -1:
                        self.zones[self.selected_zone_idx].invert_logic = not self.zones[self.selected_zone_idx].invert_logic
                    return

                bx, by, bw, bh = self.btn_delay
                if bx <= x <= bx+bw and by <= y <= by+bh:
                    if self.selected_zone_idx != -1:
                        self.input_focus = 'DELAY'
                        self.input_text = str(self.zones[self.selected_zone_idx].alarm_delay_ms)
                    return
                
                bx, by, bw, bh = self.btn_method
                if bx <= x <= bx+bw and by <= y <= by+bh:
                    if self.selected_zone_idx != -1:
                        z = self.zones[self.selected_zone_idx]
                        z.edge_method = 'CANNY' if z.edge_method == 'SOBEL' else 'SOBEL'
                    return
                
                self.input_focus = None

                bx, by, bw, bh = self.btn_reset_alarm
                if bx <= x <= bx+bw and by <= y <= by+bh:
                    for z in self.zones: z.alarm_latched = False
                    return
                
                bx, by, bw, bh = self.btn_reload_cfg
                if bx <= x <= bx+bw and by <= y <= by+bh:
                    self.load_config()
                    return
                
                bx, by, bw, bh = self.btn_clear_cfg
                if bx <= x <= bx+bw and by <= y <= by+bh:
                    result = win32api.MessageBox(0, "Tem certeza que deseja apagar TODAS as zonas?\nEssa ação não pode ser desfeita.", 
                                                 "Confirmar Exclusão", win32con.MB_YESNO | win32con.MB_ICONWARNING)
                    if result == win32con.IDYES:
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
                
                max_id = -1
                for z in self.zones:
                    if z.zone_id is not None and z.zone_id > max_id:
                        max_id = z.zone_id
                new_zone.zone_id = max_id + 1
                new_zone.setup_logger(self.log_dir)
                
                new_zone.polygon.append([x, y])
                self.zones.append(new_zone)
                self.selected_zone_idx = len(self.zones) - 1
                self.drawing_active = True
                self.refresh_trackbars()

        elif event == cv2.EVENT_RBUTTONDOWN:
            if not self.drawing_active:
                clicked_zone = -1
                for i, zone in enumerate(self.zones):
                    if len(zone.polygon) > 2:
                        poly_np = np.array(zone.polygon, dtype=np.int32)
                        if cv2.pointPolygonTest(poly_np, (x,y), False) >= 0:
                            clicked_zone = i
                            break
                
                if clicked_zone != -1:
                    self.selected_zone_idx = clicked_zone
                    self.refresh_trackbars()
                else:
                    self.selected_zone_idx = -1
                    try: cv2.destroyWindow(self.ctrl_window)
                    except: pass

    def refresh_trackbars(self):
        if self.selected_zone_idx != -1:
            if cv2.getWindowProperty(self.ctrl_window, cv2.WND_PROP_VISIBLE) < 1:
                cv2.namedWindow(self.ctrl_window, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(self.ctrl_window, 400, 150)
                cv2.moveWindow(self.ctrl_window, 20, 200)
            
            def on_sens(val):
                if self.selected_zone_idx != -1: self.zones[self.selected_zone_idx].sensitivity = val
            def on_limit(val):
                if self.selected_zone_idx != -1: self.zones[self.selected_zone_idx].alarm_limit = val
            
            z = self.zones[self.selected_zone_idx]
            cv2.createTrackbar("Sensibilidade", self.ctrl_window, z.sensitivity, 255, on_sens)
            cv2.createTrackbar("Limite Alarm", self.ctrl_window, z.alarm_limit, 5000, on_limit)
            
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
                 win32gui.SetLayeredWindowAttributes(hwnd, 0, self.edit_opacity, win32con.LWA_ALPHA)

        while self.running:
            sct_img = self.sct.grab(self.monitor_area)
            frame = np.array(sct_img)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # --- MODO EDIÇÃO: UI DE CONTROLE ---
            if not self.mode_monitor:
                if cv2.getWindowProperty(opacity_window, cv2.WND_PROP_VISIBLE) < 1:
                     cv2.namedWindow(opacity_window, cv2.WINDOW_NORMAL)
                     cv2.resizeWindow(opacity_window, 300, 60)
                     cv2.moveWindow(opacity_window, 20, 20)
                     cv2.createTrackbar("Alpha", opacity_window, self.edit_opacity, 255, on_opacity)
                     
                     hwnd_op = win32gui.FindWindow(None, opacity_window)
                     if hwnd_op:
                        win32gui.SetWindowPos(hwnd_op, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                
                self.update_window_style(alpha_val=self.edit_opacity)
            else:
                try: cv2.destroyWindow(opacity_window)
                except: pass
                self.update_window_style()

            # --- PROCESSAMENTO E DESENHO ---
            for z in self.zones:
                z.process(frame_gray, self.width, self.height)
            
            overlay = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            
            # Desenha zonas: passando o modo correto
            is_config_mode = not self.mode_monitor
            for i, z in enumerate(self.zones):
                z.draw(overlay, is_config_mode=is_config_mode)
                
            # UI Textos e Botões (somente no modo edição)
            if not self.mode_monitor:
                cv2.rectangle(overlay, (0, 0), (self.width, 150), (30, 30, 30), -1)
                
                cv2.putText(overlay, "MODO EDICAO (TAB para sair)", (self.width//2 - 130, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                cv2.putText(overlay, "Botao Dir: Selecionar | Ctrl+O: Terminar Desenho | Ctrl+J: Sair", 
                            (self.width//2 - 300, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
                
                # Botão Reset Alarm
                bx, by, bw, bh = self.btn_reset_alarm
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), (0, 0, 150), -1)
                cv2.putText(overlay, "RESET ALARME", (bx+10, by+25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                # Botão Reload Config
                bx, by, bw, bh = self.btn_reload_cfg
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), (0, 150, 150), -1)
                cv2.putText(overlay, "RELOAD CONFIG", (bx+10, by+25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                # Botão Clear Config
                bx, by, bw, bh = self.btn_clear_cfg
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), (0, 0, 0), -1)
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), (0, 0, 255), 1)
                cv2.putText(overlay, "APAGAR TUDO", (bx+10, by+25), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

                z = None
                if self.selected_zone_idx != -1:
                    z = self.zones[self.selected_zone_idx]

                # Invert Logic
                bx, by, bw, bh = self.btn_inv_logic
                if z:
                    inv_color = (0, 0, 150) if z.invert_logic else (0, 100, 0)
                    txt = "LOGIC:INV" if z.invert_logic else "LOGIC:NRM"
                else:
                    inv_color = (50, 50, 50)
                    txt = "LOGIC:--"
                
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), inv_color, -1)
                cv2.putText(overlay, txt, (bx+5, by+25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

                # Delay Input
                bx, by, bw, bh = self.btn_delay
                if z:
                    if self.input_focus == 'DELAY':
                        delay_bg = (200, 100, 0)
                        delay_txt = self.input_text + "|"
                    else:
                        delay_bg = (100, 100, 100)
                        delay_txt = f"DLY:{z.alarm_delay_ms}ms"
                else:
                    delay_bg = (50, 50, 50)
                    delay_txt = "DELAY:--"
                
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), delay_bg, -1)
                cv2.putText(overlay, delay_txt, (bx+5, by+25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

                # Method Button
                bx, by, bw, bh = self.btn_method
                if z:
                    if z.edge_method == 'CANNY':
                        meth_bg = (128, 0, 128)
                        meth_txt = "ALG:CANNY"
                    else:
                        meth_bg = (100, 0, 0)
                        meth_txt = "ALG:SOBEL"
                else:
                    meth_bg = (50, 50, 50)
                    meth_txt = "ALG:--"
                
                cv2.rectangle(overlay, (bx, by), (bx+bw, by+bh), meth_bg, -1)
                cv2.putText(overlay, meth_txt, (bx+5, by+25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            
            cv2.imshow(self.window_name, overlay)
            
            key = cv2.waitKey(1) & 0xFF
            
            # --- INPUT TEXT HANDLING ---
            if self.input_focus == 'DELAY':
                if 48 <= key <= 57: # 0-9
                    self.input_text += chr(key)
                elif key == 8: # Backspace
                    self.input_text = self.input_text[:-1]
                elif key == 13: # Enter
                    if self.selected_zone_idx != -1 and self.input_text.isdigit():
                         self.zones[self.selected_zone_idx].alarm_delay_ms = int(self.input_text)
                    self.input_focus = None
                elif key == 27: # Esc
                    self.input_focus = None
                
                continue

            
            if key == 9: # TAB
                self.mode_monitor = not self.mode_monitor
                self.drawing_active = False 
                if self.mode_monitor: self.selected_zone_idx = -1
            
            if key == 15: # Ctrl+O
                if self.drawing_active:
                    self.drawing_active = False
                    if self.selected_zone_idx != -1 and len(self.zones[self.selected_zone_idx].polygon) < 3:
                        self.zones.pop(self.selected_zone_idx)
                        self.selected_zone_idx = -1
                        try: cv2.destroyWindow(self.ctrl_window)
                        except: pass
                    print("Desenho finalizado via Ctrl+O")
            
            if key == 10: # Ctrl+J
                self.running = False

            if key in [127, 46]: # Delete
                 if not self.mode_monitor and self.selected_zone_idx != -1:
                     self.zones.pop(self.selected_zone_idx)
                     self.selected_zone_idx = -1
                     self.refresh_trackbars()

        self.save_config()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    app = App()
    app.run()
