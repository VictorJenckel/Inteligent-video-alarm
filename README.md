# 🛡️ OverlayAlarm — Sistema Inteligente de Alarme por Visão Computacional

> **Solução de monitoramento em tempo real para detecção de violação de vidros, barreiras físicas e áreas de segurança, diretamente sobre a tela do Windows — sem câmeras externas.**

---

## 📌 O Que É

O **OverlayAlarm** é um sistema de alarme baseado em **visão computacional** que roda como um **overlay transparente sobre o monitor** do Windows. Ele captura a tela em tempo real, aplica algoritmos de detecção de borda dentro de zonas configuráveis pelo usuário e dispara alarmes automaticamente quando detecta alterações físicas na cena — como quebra de vidro, remoção de objetos ou intrusão em áreas monitoradas.

O sistema é **totalmente autônomo**: sem servidores, sem internet, sem câmeras IP — basta o executável e um monitor.

---

## 🎯 Casos de Uso

| Cenário | Descrição |
|---|---|
| **Detecção de quebra de vidro** | Monitora padrões de borda em superfícies translúcidas; alarme ao detectar ruptura |
| **Vigilância de perímetro** | Define zonas em imagens de câmeras exibidas na tela e monitora alterações |
| **Controle de acesso visual** | Detecta presença ou remoção de objetos físicos em áreas críticas |
| **Monitoramento industrial** | Acompanha continuidade de estruturas, juntas ou peças em linha de produção |
| **Segurança patrimonial** | Integra com sistemas de CFTV existentes sem necessidade de API ou hardware adicional |

---

## ⚙️ Como Funciona

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

### 🔬 Dois Algoritmos de Detecção de Borda (por zona)
| Algoritmo | Ideal para |
|---|---|
| **SOBEL** (padrão) | Detecção de bordas verticais — vidros, fitas, divisórias |
| **CANNY** | Detecção completa de contornos — objetos, peças industriais |

> Alternável por botão na interface, individualmente por zona.

### ⚡ Lógica de Alarme Configurável (por zona)
- **Modo Normal**: alarme quando o score de borda **cai abaixo** do limite (perda de borda = quebra/remoção)
- **Modo Invertido**: alarme quando o score de borda **supera** o limite (aparecimento de borda = intrusão)
- **Delay configurável**: define um tempo mínimo (em ms) para que o alarme seja confirmado, evitando falsos positivos por variações momentâneas

### 🔒 Sistema de Alarme com Latch (Trava)
- Ao disparar, o alarme **permanece ativo** mesmo que a condição de alerta cesse
- Requer **reset manual** pelo operador, garantindo que nenhum evento passe despercebido
- Reset disponível por botão na interface

### 📊 Barra de Nível em Tempo Real (modo edição)
- Exibe o **score atual de bordas** visualmente para cada zona
- Linha amarela indica o **limite de alarme** configurado
- Auxilia na calibração rápida da sensibilidade em campo

### 📝 Sistema de Logs por Zona
- Gera arquivos **`area_N_log.txt`** individuais para cada zona monitorada
- Logs gerados **apenas quando há alarme ativo** (sem desperdício de disco)
- Rate limit de **1 registro por segundo** durante alarme persistente
- Pasta `logs/` criada automaticamente ao lado do executável
- Formato de log:
  ```
  2026-03-26 05:42:11 | ALARM ACTIVE | Score: 87 | Limit: 500
  ```

### 🪟 Overlay Nativo do Windows
- Janela **sempre no topo** (`HWND_TOPMOST`)
- No modo monitor: **100% transparente ao clique** (`WS_EX_TRANSPARENT`) — o mouse passa direto para as aplicações em baixo
- **Anti-Capture**: o overlay é invisível para a captura de tela (sem loop de feedback)
- Opacidade ajustável em tempo real no modo edição (0–255)

---

## 🖥️ Interface — Botões do Modo Edição

| Botão | Função |
|---|---|
| `RESET ALARME` | Desfaz o latch de todas as zonas |
| `RELOAD CONFIG` | Recarrega zonas do arquivo JSON (sem reiniciar) |
| `APAGAR TUDO` | Remove todas as zonas (com confirmação) |
| `LOGIC:NRM / INV` | Alterna lógica normal/invertida da zona selecionada |
| `DLY:Xms` | Define delay de confirmação de alarme (teclado numérico) |
| `ALG:SOBEL / CANNY` | Alterna o algoritmo de detecção da zona selecionada |

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

```
📂 Pasta do executável/
├── 📄 OverlayAlarm_2026-03-26.exe    ← Executável standalone
├── 📄 overlay_config.json             ← Configuração das zonas (salvo automaticamente)
└── 📂 logs/
    ├── 📄 area_0_log.txt              ← Log de eventos da Zona 0
    ├── 📄 area_1_log.txt              ← Log de eventos da Zona 1
    └── 📄 area_N_log.txt              ← ...
```

---

## 🔧 Especificações Técnicas

| Item | Detalhe |
|---|---|
| **Linguagem** | Python 3.13 |
| **Distribuição** | PyInstaller — `.exe` standalone, sem dependências externas |
| **Visão computacional** | OpenCV 4.13 |
| **Captura de tela** | MSS (Multi-Screen Shot) — alta performance |
| **Interface Windows** | pywin32 (win32gui, win32con, win32api) |
| **Logging** | Python `logging` nativo, arquivos `.txt` com encoding UTF-8 |
| **Sistema operacional** | Windows 10 / 11 (64-bit) |
| **Processamento** | CPU — sem necessidade de GPU |

---

## 📐 Parâmetros de Configuração por Zona

| Parâmetro | Faixa | Descrição |
|---|---|---|
| **Sensibilidade** | 0–255 | Limiar do filtro de borda; quanto menor, mais bordas são detectadas |
| **Limite de Alarme** | 0–5000 | Quantidade mínima (ou máxima, no modo invertido) de pixels de borda |
| **Delay** | 0–∞ ms | Tempo de confirmação antes do alarme ser validado |
| **Algoritmo** | SOBEL / CANNY | Método de detecção de bordas |
| **Lógica** | Normal / Invertida | Direção do gatilho de alarme |

---

## 🚀 Como Usar

1. **Execute** `OverlayAlarm_2026-03-26.exe`
2. Pressione **`TAB`** para entrar no **Modo Edição**
3. **Clique com botão esquerdo** na tela para começar a desenhar uma zona de monitoramento
4. Continue clicando para adicionar vértices ao polígono
5. Pressione **`Ctrl+O`** para finalizar o polígono
6. Ajuste **Sensibilidade** e **Limite** nos sliders da janela "Ajustes"
7. Pressione **`TAB`** novamente para voltar ao **Modo Monitor**
8. O overlay some e a detecção roda silenciosamente em background
9. Ao detectar um alarme, um **ponto vermelho** aparece no centro da zona afetada
10. Os eventos são gravados na pasta **`logs/`**

---

*Sistema desenvolvido para ambientes Windows. Distribuição como executável standalone — não requer instalação de Python ou dependências.*
