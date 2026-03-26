# 🛡️ OverlayAlarm — Sistema Inteligente de Alarme por Visão Computacional

<p align="center">
  <img src="https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54" />
  <img src="https://img.shields.io/badge/opencv-%23white.svg?style=for-the-badge&logo=opencv&logoColor=white" />
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" />
</p>

> **Solução de monitoramento em tempo real para detecção de violação de vidros, barreiras físicas e áreas de segurança, diretamente sobre a tela do Windows — sem câmeras externas.**

---

## 📌 O Que É

O **OverlayAlarm** é um sistema de alarme baseado em **visão computacional** que roda como um **overlay transparente sobre o monitor** do Windows. Ele captura a tela em tempo real, aplica algoritmos de detecção de borda e/ou fluxo óptico dentro de zonas configuráveis pelo usuário e dispara alarmes automaticamente quando detecta alterações físicas na cena — como quebra de vidro, remoção de objetos ou intrusão em áreas monitoradas.

O sistema é **totalmente autônomo**: sem servidores, sem internet, sem câmeras IP — basta o executável e um monitor.

O projeto conta com **duas versões** do executável, cada uma com diferentes capacidades de detecção:

| Versão | Executável | Motor de detecção |
|---|---|---|
| **Standard** | `OverlayAlarm_2026-03-26.exe` | Detecção por bordas (Sobel/Canny) |
| **Flow Analizer** | `OverlayAlarm_FlowAnalizer.exe` | Bordas + **Optical Flow** + Snapshots automáticos |

---

## 🎯 Casos de Uso

| Cenário | Descrição |
|---|---|
| **Detecção de quebra de vidro** | Monitora padrões de borda em superfícies translúcidas; alarme ao detectar ruptura |
| **Vigilância de perímetro** | Define zonas em imagens de câmeras exibidas na tela e monitora alterações |
| **Controle de acesso visual** | Detecta presença ou remoção de objetos físicos em áreas críticas |
| **Monitoramento industrial** | Acompanha continuidade de estruturas, juntas ou peças em linha de produção |
| **Segurança patrimonial** | Integra com sistemas de CFTV existentes sem necessidade de API ou hardware adicional |
| **Detecção de movimento** *(Flow Analizer)* | Detecta deslocamento físico real na cena, mesmo sem perda de bordas |

---

## ⚙️ Como Funciona

### Versão Standard

```
[Tela do Monitor]
       │
       ▼
[Captura em tempo real via MSS]
       │
       ▼
[Conversão para escala de cinza]
       │
       ▼
[Detecção de bordas (Sobel ou Canny) dentro da zona definida]
       │
       ▼
[Cálculo do Score de Borda]
       │
  ┌────┴────┐
  │         │
Score OK  Score < Limite
  │         │
  ▼         ▼
 Normal   ALARME DISPARADO
            │
            ├── Visual: ponto vermelho na zona
            ├── Persistência: alarme travado (latch)
            └── Log: registro em arquivo .txt
```

### Versão Flow Analizer *(motor duplo)*

```
[Captura + Frame Cinza]
       │
  ┌────┴──────────────────┐
  │                       │
  ▼                       ▼
[Detecção de Bordas]  [Optical Flow Farneback]
  │                    (thread daemon separada)
  │                       │
  ▼                       ▼
[Score > Limite?]   [Média móvel px/frame > Limiar?]
  │                       │
  └──────── OR ───────────┘
                │
          ALARME DISPARADO
                │
                ├── Visual: ponto vermelho
                ├── Latch (trava persistente)
                ├── Log com dados de Sobel + Flow
                └── Snapshot JPEG automático (a cada 5s)
```

---

## 🚀 Capacidades e Funcionalidades

### 🖱️ Zonas de Monitoramento
- **Criação livre de polígonos**: clique para adicionar vértices e forme qualquer área de monitoramento — retângulos, triângulos, formas irregulares
- **Múltiplas zonas simultâneas**: sem limite fixo de quantidade de áreas
- **Persistência automática**: zonas salvas em `overlay_config.json` e recarregadas na próxima execução
- **Seleção interativa**: clique com botão direito dentro de uma zona para selecioná-la e ajustá-la individualmente

### 🧠 Dois Modos de Operação
| Modo | Ativação | Comportamento |
|---|---|---|
| **Monitor** | Padrão ao iniciar | Overlay 100% transparente ao mouse; detecção ativa em background; exibe só o ponto de alarme |
| **Edição (TAB)** | Tecla `TAB` | Interface visível com botões, barra de nível e contornos das zonas |

### 🔬 Algoritmos de Detecção de Borda (por zona)
| Algoritmo | Ideal para |
|---|---|
| **SOBEL** (padrão) | Detecção de bordas verticais — vidros, fitas, divisórias |
| **CANNY** | Detecção completa de contornos — objetos, peças industriais |

> Alternável por botão na interface, individualmente por zona.

### 🌊 Optical Flow — *exclusivo do Flow Analizer*
- Algoritmo **Farneback Dense Optical Flow** rodando em **thread daemon separada** por zona
- Detecta **movimento real de pixels** — vibração, deslocamento, intrusão — mesmo sem alteração de bordas
- **Média móvel** sobre janela de 15 frames para evitar falsas detecções por variações pontuais
- Calibrado para cenas reais: fluxo estático ≈ `0.31 px/frame`; evento ≈ `1.13 px/frame`; limiar padrão: `0.60 px/frame`
- **Pode ser ligado/desligado individualmente** por zona sem reiniciar o sistema
- Limiar ajustável por trackbar em tempo real (`Flow px/f x100`)

### ⚡ Lógica de Alarme Configurável (por zona)
- **Modo Normal**: alarme quando o score de borda **cai abaixo** do limite (perda de borda = quebra/remoção)
- **Modo Invertido**: alarme quando o score de borda **supera** o limite (aparecimento de borda = intrusão)
- **Delay configurável**: define um tempo mínimo (em ms) para que o alarme seja confirmado, evitando falsos positivos por variações momentâneas
- *(Flow Analizer)* Alarme por borda **OR** por movimento — qualquer detector que acusar dispara

### 🔒 Sistema de Alarme com Latch (Trava)
- Ao disparar, o alarme **permanece ativo** mesmo que a condição de alerta cesse
- Requer **reset manual** pelo operador, garantindo que nenhum evento passe despercebido
- Reset disponível por botão na interface; *(Flow Analizer)* também reseta o histórico do fluxo

### 📸 Snapshots Automáticos — *exclusivo do Flow Analizer*
- A cada alarme, salva automaticamente uma **imagem JPEG** recortada da bounding box da zona
- Intervalo: **1 captura a cada 5 segundos** enquanto o alarme permanecer ativo
- Nome do arquivo inclui zona, timestamp e valor de fluxo: `zona0_20260326_054211_flow0.73.jpg`
- Armazenadas em `logs/snapshots/`

### 📊 Barra de Nível em Tempo Real (modo edição)
- Exibe o **score atual de bordas** visualmente para cada zona
- Linha amarela indica o **limite de alarme** configurado
- *(Flow Analizer)* exibe também o valor de fluxo atual e limiar (`FLOW 0.42/0.60`)
- Auxilia na calibração rápida da sensibilidade em campo

### 📝 Sistema de Logs por Zona
- Gera arquivos **`area_N_log.txt`** individuais para cada zona monitorada
- Logs gerados **apenas quando há alarme ativo** (sem desperdício de disco)
- Rate limit de **1 registro por segundo** durante alarme persistente
- Pasta `logs/` criada automaticamente ao lado do executável

**Formato — Versão Standard:**
```
2026-03-26 05:42:11 | ALARM ACTIVE | Score: 87 | Limit: 500
```

**Formato — Versão Flow Analizer:**
```
2026-03-26 05:42:11 | ALARM | Sobel=87 | SobelLimit=500 | Flow_avg=0.734px/f | Flow_inst=0.891px/f | FlowThresh=0.60px/f
```

### 🪟 Overlay Nativo do Windows
- Janela **sempre no topo** (`HWND_TOPMOST`)
- No modo monitor: **100% transparente ao clique** (`WS_EX_TRANSPARENT`) — o mouse passa direto para as aplicações em baixo
- **Anti-Capture**: o overlay é invisível para a captura de tela (sem loop de feedback)
- Opacidade ajustável em tempo real no modo edição (0–255)

---

## 🖥️ Interface — Botões do Modo Edição

| Botão | Versão | Função |
|---|---|---|
| `RESET ALARME` | Ambas | Desfaz o latch de todas as zonas |
| `RELOAD CONFIG` | Ambas | Recarrega zonas do arquivo JSON (sem reiniciar) |
| `APAGAR TUDO` | Ambas | Remove todas as zonas (com confirmação) |
| `LOGIC:NRM / INV` | Ambas | Alterna lógica normal/invertida da zona selecionada |
| `DLY:Xms` | Ambas | Define delay de confirmação de alarme (teclado numérico) |
| `ALG:SOBEL / CANNY` | Ambas | Alterna o algoritmo de detecção da zona selecionada |
| `FLOW:ON / OFF` | Flow Analizer | Liga/desliga o detector de fluxo óptico da zona selecionada |

---

## ⌨️ Atalhos de Teclado

| Tecla | Ação |
|---|---|
| `TAB` | Alterna entre Modo Monitor e Modo Edição |
| `Ctrl+O` | Finaliza o desenho do polígono atual |
| `Delete` | Remove a zona selecionada |
| `Ctrl+J` | Encerra o programa (salva config automaticamente) |
| `0–9`, `Backspace`, `Enter` | Entrada numérica do delay (quando campo ativo) |
| `Esc` | Cancela entrada de texto |

---

## 📁 Arquivos Gerados

### Versão Standard
```
📂 Pasta do executável/
├── 📄 OverlayAlarm_2026-03-26.exe     ← Executável standalone
├── 📄 overlay_config.json              ← Configuração das zonas (salvo automaticamente)
└── 📂 logs/
    ├── 📄 area_0_log.txt               ← Log de eventos da Zona 0
    ├── 📄 area_1_log.txt               ← Log de eventos da Zona 1
    └── 📄 area_N_log.txt               ← ...
```

### Versão Flow Analizer
```
📂 Pasta do executável/
├── 📄 OverlayAlarm_FlowAnalizer.exe   ← Executável standalone
├── 📄 overlay_config.json              ← Configuração das zonas (salvo automaticamente)
└── 📂 logs/
    ├── 📄 area_0_log.txt               ← Log de eventos + dados de fluxo da Zona 0
    ├── 📄 area_N_log.txt               ← ...
    └── 📂 snapshots/
        ├── 🖼️ zona0_20260326_054211_flow0.73.jpg  ← Imagem capturada no alarme
        └── 🖼️ zona1_20260326_054415_flow1.12.jpg  ← ...
```

---

## 🔧 Especificações Técnicas

| Item | Detalhe |
|---|---|
| **Linguagem** | Python 3.13 |
| **Distribuição** | PyInstaller — `.exe` standalone, sem dependências externas |
| **Visão computacional** | OpenCV 4.13 |
| **Optical Flow** | Farneback Dense Optical Flow (OpenCV) — thread daemon por zona |
| **Captura de tela** | MSS (Multi-Screen Shot) — alta performance |
| **Interface Windows** | pywin32 (win32gui, win32con, win32api) |
| **Logging** | Python `logging` nativo, arquivos `.txt` com encoding UTF-8 |
| **Sistema operacional** | Windows 10 / 11 (64-bit) |
| **Processamento** | CPU — sem necessidade de GPU |

---

## 📐 Parâmetros de Configuração por Zona

| Parâmetro | Faixa | Versões | Descrição |
|---|---|---|---|
| **Sensibilidade** | 0–255 | Ambas | Limiar do filtro de borda; quanto menor, mais bordas são detectadas |
| **Limite de Alarme** | 0–5000 | Ambas | Quantidade mínima (ou máxima, no modo invertido) de pixels de borda |
| **Delay** | 0–∞ ms | Ambas | Tempo de confirmação antes do alarme ser validado |
| **Algoritmo** | SOBEL / CANNY | Ambas | Método de detecção de bordas |
| **Lógica** | Normal / Invertida | Ambas | Direção do gatilho de alarme |
| **Flow Threshold** | 0–200 (×0.01 px/f) | Flow Analizer | Limiar de fluxo óptico para disparo de alarme por movimento |
| **Flow Habilitado** | ON / OFF | Flow Analizer | Liga/desliga o detector de fluxo por zona individualmente |

---

## 🚀 Como Usar

1. **Execute** o `.exe` desejado (`Standard` ou `Flow Analizer`)
2. Pressione **`TAB`** para entrar no **Modo Edição**
3. **Clique com botão esquerdo** na tela para começar a desenhar uma zona de monitoramento
4. Continue clicando para adicionar vértices ao polígono
5. Pressione **`Ctrl+O`** para finalizar o polígono
6. Ajuste **Sensibilidade**, **Limite** e *(Flow Analizer)* **Flow Threshold** nos sliders da janela "Ajustes"
7. Pressione **`TAB`** novamente para voltar ao **Modo Monitor**
8. O overlay some e a detecção roda silenciosamente em background
9. Ao detectar um alarme, um **ponto vermelho** aparece no centro da zona afetada
10. Os eventos são gravados na pasta **`logs/`** e *(Flow Analizer)* snapshots em `logs/snapshots/`

---

## ⚖️ Comparativo das Versões

| Capacidade | Standard | Flow Analizer |
|---|---|---|
| Detecção por bordas (Sobel/Canny) | ✅ | ✅ |
| Lógica Normal/Invertida | ✅ | ✅ |
| Delay de confirmação | ✅ | ✅ |
| Alarme com Latch | ✅ | ✅ |
| Logs por zona | ✅ | ✅ |
| Optical Flow em thread separada | ❌ | ✅ |
| Alarme por movimento (sem perda de borda) | ❌ | ✅ |
| Snapshot JPEG automático no alarme | ❌ | ✅ |
| Log com dados de fluxo óptico | ❌ | ✅ |
| Controle de Flow por zona | ❌ | ✅ |

---

*Sistema desenvolvido para ambientes Windows. Distribuição como executável standalone — não requer instalação de Python ou dependências.*
