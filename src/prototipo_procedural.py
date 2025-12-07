import cv2
import numpy as np
import mediapipe as mp
from math import dist
import threading
import winsound
import time

# ------------------------------------
# FUNÇÃO PARA TEXTO NO HUD
# ------------------------------------
def draw_text(img, text, x, y, color=(255,255,255), scale=0.6):
    cv2.putText(img, text, (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)

# ------------------------------------
# CONFIGURAÇÕES
# ------------------------------------
FRAMES_CALIBRACAO = 20
FATOR_FECHADO = 0.80
SUAVIZACAO = 0.2

ALARME_ATIVO = False
FRAMES_PISCAR = 0

# Histórico EAR para o gráfico
EAR_HISTORY = []
HIST_MAX = 100  # tamanho do gráfico

# ------------------------------------
# ALARME
# ------------------------------------
def loop_alarme():
    global ALARME_ATIVO
    while ALARME_ATIVO:
        winsound.Beep(1500, 500)

def iniciar_alarme():
    global ALARME_ATIVO
    if not ALARME_ATIVO:
        ALARME_ATIVO = True
        threading.Thread(target=loop_alarme, daemon=True).start()

def parar_alarme():
    global ALARME_ATIVO
    ALARME_ATIVO = False

# ------------------------------------
# MEDIAPIPE
# ------------------------------------
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    refine_landmarks=True,
    max_num_faces=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

RIGHT_EYE = [33, 160, 158, 133, 153, 144]

# EAR
def EAR(pts):
    A = dist(pts[1], pts[5])
    B = dist(pts[2], pts[4])
    C = dist(pts[0], pts[3])
    return (A + B) / (2.0 * C)

# ------------------------------------
# CÂMERA
# ------------------------------------
cap = cv2.VideoCapture(0)

fps = cap.get(cv2.CAP_PROP_FPS)
if fps == 0 or fps is None or fps != fps:
    fps = 30

FRAMES_PISCAR = int(fps * 1.0)

cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

# ------------------------------------
# VARIÁVEIS
# ------------------------------------
ear_suave = None
calibrando = True
frames = 0
soma_ear = 0
limiar_fechado = 0
frames_fechado = 0

mensagem_status = "Calibrando..."
mensagem_limite = ""

# ------------------------------------
# LOOP PRINCIPAL
# ------------------------------------
while True:
    ok, frame = cap.read()
    if not ok:
        break

    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)

    if results.multi_face_landmarks:
        face = results.multi_face_landmarks[0]

        olho = [(int(face.landmark[i].x * w),
                 int(face.landmark[i].y * h)) for i in RIGHT_EYE]

        ear = EAR(olho)

        if ear_suave is None:
            ear_suave = ear
        else:
            ear_suave = ear_suave * (1 - SUAVIZACAO) + ear * SUAVIZACAO

        # Registrar no gráfico
        EAR_HISTORY.append(ear_suave)
        if len(EAR_HISTORY) > HIST_MAX:
            EAR_HISTORY.pop(0)

        # -------- CALIBRAÇÃO --------
        if calibrando:
            frames += 1
            soma_ear += ear_suave

            mensagem_status = f"Calibrando... {frames}/{FRAMES_CALIBRACAO}"

            if frames >= FRAMES_CALIBRACAO:
                ear_aberto = soma_ear / frames
                limiar_fechado = ear_aberto * FATOR_FECHADO
                calibrando = False

                mensagem_status = "Calibração concluída!"
                mensagem_limite = f"Limiar: {limiar_fechado:.2f}"

        # -------- DETECÇÃO --------
        else:
            aberto = ear_suave > limiar_fechado

            if not aberto:
                frames_fechado += 1
            else:
                frames_fechado = 0
                parar_alarme()

            if frames_fechado >= FRAMES_PISCAR:
                iniciar_alarme()

            mensagem_status = "OLHO ABERTO" if aberto else "OLHO FECHADO"
            mensagem_limite = f"EAR: {ear_suave:.2f}"

        # Pontos do olho
        for p in olho:
            cv2.circle(frame, p, 2, (255, 0, 0), -1)

    # ----------------------------------------------------
    # HUD LATERAL
    # ----------------------------------------------------
    HUD_W = 350
    overlay = np.zeros((h, HUD_W, 3), dtype=np.uint8)
    overlay[:] = (0, 0, 0)

    y = 40
    draw_text(overlay, f"FPS: {fps:.1f}", 20, y); y += 30
    draw_text(overlay, f"Res: {cam_w}x{cam_h}", 20, y); y += 30

    # Status
    cor = (0,255,0) if "ABERTO" in mensagem_status else (0,0,255)
    draw_text(overlay, mensagem_status, 20, y, cor); y += 30
    draw_text(overlay, mensagem_limite, 20, y, (255,255,0)); y += 40

    # ----------------------------------------------------
    # GRÁFICO DO EAR
    # ----------------------------------------------------
    graph_h = 120
    graph_w = HUD_W - 40
    gx, gy = 20, y

    cv2.rectangle(overlay, (gx, gy), (gx + graph_w, gy + graph_h), (40, 40, 40), -1)

    if len(EAR_HISTORY) > 1:
        pts = []
        for i, v in enumerate(EAR_HISTORY):
            px = gx + int(i / HIST_MAX * graph_w)
            py = gy + graph_h - int(v * graph_h * 2)  # amplifica gráfico
            pts.append((px, py))

        for i in range(1, len(pts)):
            cv2.line(overlay, pts[i - 1], pts[i], (0, 255, 255), 2)

    y += graph_h + 40

    # ----------------------------------------------------
    # BARRA DE TEMPO PARA FECHAR O OLHO
    # ----------------------------------------------------
    pct = frames_fechado / FRAMES_PISCAR
    pct = max(0, min(1, pct))

    BAR_W = HUD_W - 40
    BAR_H = 20
    bx, by = 20, y

    cv2.rectangle(overlay, (bx, by), (bx + BAR_W, by + BAR_H), (100, 100, 100), -1)
    cv2.rectangle(overlay, (bx, by), (bx + int(BAR_W*pct), by + BAR_H), (0, 0, 255), -1)

    # Juntar HUD + câmera
    final = np.hstack([frame, overlay])

    cv2.imshow("Anti-Sono", final)

    if cv2.waitKey(1) == 27:
        break

# FIM
parar_alarme()
cap.release()
cv2.destroyAllWindows()
