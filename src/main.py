import cv2
import numpy as np
import mediapipe as mp
from math import dist
import threading
import winsound
import time
from collections import deque
from typing import Tuple, List

# -----------------------------
# Configurações gerais
# -----------------------------
FRAMES_CALIBRACAO = 20
FATOR_FECHADO = 0.80
SUAVIZACAO = 0.2
HIST_MAX = 100


# -----------------------------
# CameraManager
# -----------------------------
class CameraManager:
    def __init__(self, index: int = 0, width: int = None, height: int = None):
        self.cap = cv2.VideoCapture(index)
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        time.sleep(0.5)

    def read(self):
        return self.cap.read()

    def get_fps(self) -> float:
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps:
            fps = 30.0
        return float(fps)

    def get_resolution(self) -> Tuple[int, int]:
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h

    def release(self):
        self.cap.release()


# -----------------------------
# EARCalculator
# -----------------------------
class EARCalculator:
    def __init__(self, eye_indices: List[int]):
        self.eye_indices = eye_indices

    @staticmethod
    def compute_EAR(pts: List[Tuple[int, int]]) -> float:
        A = dist(pts[1], pts[5])
        B = dist(pts[2], pts[4])
        C = dist(pts[0], pts[3])
        if C == 0:
            return 0.0
        return (A + B) / (2.0 * C)


# -----------------------------
# BlinkDetector (gerencia calibração / contagem)
# -----------------------------
class BlinkDetector:
    def __init__(self, frames_calibracao=FRAMES_CALIBRACAO, fator_fechado=FATOR_FECHADO):
        self.frames_calibracao = frames_calibracao
        self.fator_fechado = fator_fechado

        self.calibrando = True
        self._frames = 0
        self._soma_ear = 0.0
        self.ear_aberto_medio = None
        self.limiar_fechado = None

        self.frames_fechado = 0

    def update_calibration(self, ear_value: float):
        if not self.calibrando:
            return
        self._frames += 1
        self._soma_ear += ear_value
        if self._frames >= self.frames_calibracao:
            self.ear_aberto_medio = self._soma_ear / self._frames
            self.limiar_fechado = self.ear_aberto_medio * self.fator_fechado
            self.calibrando = False

    def reset_calibration(self):
        self.calibrando = True
        self._frames = 0
        self._soma_ear = 0.0
        self.ear_aberto_medio = None
        self.limiar_fechado = None

    def update_detection(self, ear_value: float) -> Tuple[bool, float]:
        """
        Atualiza contador interno e retorna (aberto_bool, limiar_atual)
        """
        if self.calibrando:
            self.update_calibration(ear_value)
            return True, None

        aberto = ear_value > self.limiar_fechado
        if not aberto:
            self.frames_fechado += 1
        else:
            self.frames_fechado = 0
        return aberto, self.limiar_fechado


# -----------------------------
# AlarmSystem
# -----------------------------
class AlarmSystem:
    def __init__(self, freq=1500, duration_ms=500):
        self._active = False
        self.freq = freq
        self.duration_ms = duration_ms
        self._thread = None

    def _loop_beep(self):
        while self._active:
            winsound.Beep(self.freq, self.duration_ms)

    def start(self):
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(target=self._loop_beep, daemon=True)
        self._thread.start()

    def stop(self):
        self._active = False
        # thread é daemon; irá encerrar sozinha


# -----------------------------
# HUDRenderer
# -----------------------------
class HUDRenderer:
    def __init__(self, hud_width: int = 350, hist_max: int = HIST_MAX):
        self.hud_w = hud_width
        self.hist_max = hist_max
        self.ear_history = deque(maxlen=hist_max)

    def push_ear(self, value: float):
        self.ear_history.append(value)

    def render(self, frame: np.ndarray, fps: float, res: Tuple[int, int],
               status_text: str, threshold_text: str, frames_closed: int, frames_needed: int):
        """
        Retorna imagem combinada (frame + hud).
        """
        h, w = frame.shape[:2]
        overlay = np.zeros((h, self.hud_w, 3), dtype=np.uint8)

        # topo: FPS e resolução
        y = 40
        self._draw_text(overlay, f"FPS: {fps:.1f}", 20, y); y += 30
        self._draw_text(overlay, f"Res: {res[0]}x{res[1]}", 20, y); y += 30
        self._draw_text(overlay, f"1s = {frames_needed} frames", 20, y); y += 40

        # status
        color = (0, 255, 0) if "ABERTO" in status_text else (0, 0, 255)
        self._draw_text(overlay, status_text, 20, y, color); y += 30
        self._draw_text(overlay, threshold_text, 20, y, (255, 255, 0)); y += 40

        # gráfico do EAR
        graph_h = 120
        graph_w = self.hud_w - 40
        gx, gy = 20, y
        cv2.rectangle(overlay, (gx, gy), (gx + graph_w, gy + graph_h), (40, 40, 40), -1)

        if len(self.ear_history) > 1:
            pts = []
            for i, v in enumerate(self.ear_history):
                px = gx + int(i / self.hist_max * graph_w)
                py = gy + graph_h - int(v * graph_h * 2)
                pts.append((px, py))
            for i in range(1, len(pts)):
                cv2.line(overlay, pts[i - 1], pts[i], (0, 255, 255), 2)

        y += graph_h + 30

        # barra de progresso
        pct = (frames_closed / frames_needed) if frames_needed > 0 else 0.0
        pct = max(0.0, min(1.0, pct))

        BAR_W = self.hud_w - 40
        BAR_H = 20
        bx, by = 20, y
        cv2.rectangle(overlay, (bx, by), (bx + BAR_W, by + BAR_H), (100, 100, 100), -1)
        cv2.rectangle(overlay, (bx, by), (bx + int(BAR_W * pct), by + BAR_H), (0, 0, 255), -1)
        self._draw_text(overlay, f"{int(pct*100)}%", bx + BAR_W - 60, by + BAR_H + 18, (255, 255, 255), scale=0.6)

        # combinar horizontalmente
        final = np.hstack([frame, overlay])
        return final

    @staticmethod
    def _draw_text(img, text, x, y, color=(255, 255, 255), scale=0.6):
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)


# -----------------------------
# AntiSleepController
# -----------------------------
class AntiSleepController:
    def __init__(self, cam_index=0):
        self.camera = CameraManager(cam_index)
        self.fps = self.camera.get_fps()
        self.res = self.camera.get_resolution()
        self.frames_to_alert = int(self.fps * 1.0)

        self.mp_face = mp.solutions.face_mesh
        self.face_mesh = self.mp_face.FaceMesh(refine_landmarks=True, max_num_faces=1,
                                               min_detection_confidence=0.5, min_tracking_confidence=0.5)
        self.ear_right = EARCalculator([33, 160, 158, 133, 153, 144])
        self.ear_left = EARCalculator([362, 385, 387, 263, 373, 380])

        self.detector = BlinkDetector()
        self.alarm = AlarmSystem()
        self.hud = HUDRenderer(hud_width=350, hist_max=HIST_MAX)

        self.ear_suave = None
        self.running = True

    def run(self):
        print("Iniciando Anti-Sono (pressione ESC para sair)")
        while self.running:
            ok, frame = self.camera.read()
            if not ok:
                break

            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb)

            if results.multi_face_landmarks:
                lm = results.multi_face_landmarks[0]
                pontos = np.array([[int(p.x * w), int(p.y * h)] for p in lm.landmark])

                # calcular EAR por olho
                right_pts = [tuple(pontos[i]) for i in self.ear_right.eye_indices]
                left_pts = [tuple(pontos[i]) for i in self.ear_left.eye_indices]

                ear_r = EARCalculator.compute_EAR(right_pts)
                ear_l = EARCalculator.compute_EAR(left_pts)
                ear = (ear_r + ear_l) / 2.0

                # suavização exponencial
                if self.ear_suave is None:
                    self.ear_suave = ear
                else:
                    self.ear_suave = self.ear_suave * (1 - SUAVIZACAO) + ear * SUAVIZACAO

                self.hud.push_ear(self.ear_suave)

                # atualizar detector
                if self.detector.calibrando:
                    self.detector.update_calibration(self.ear_suave)
                    status_text = f"Calibrando... {self.detector._frames}/{self.detector.frames_calibracao}"
                    threshold_text = ""
                else:
                    aberto, limiar = self.detector.update_detection(self.ear_suave)
                    status_text = "OLHO ABERTO" if aberto else "OLHO FECHADO"
                    threshold_text = f"EAR: {self.ear_suave:.3f}  LIMIAR: {limiar:.3f}"

                    # gerenciar alarme
                    if self.detector.frames_fechado >= self.frames_to_alert:
                        self.alarm.start()
                    else:
                        self.alarm.stop()

                # desenhar pontos do olho (debug)
                for idx in (self.ear_right.eye_indices + self.ear_left.eye_indices):
                    px, py = int(pontos[idx][0]), int(pontos[idx][1])
                    cv2.circle(frame, (px, py), 2, (255, 0, 0), -1)

            else:
                status_text = "Rosto nao detectado"
                threshold_text = ""

            # render HUD
            final = self.hud.render(frame, self.fps, self.res,
                                    status_text, threshold_text,
                                    self.detector.frames_fechado, self.frames_to_alert)

            cv2.imshow("Anti-Sono", final)
            if cv2.waitKey(1) == 27:
                break

        self.stop()

    def stop(self):
        self.running = False
        self.alarm.stop()
        self.face_mesh.close()
        self.camera.release()
        cv2.destroyAllWindows()


# -----------------------------
# Execução
# -----------------------------
if __name__ == "__main__":
    controller = AntiSleepController(cam_index=0)
    controller.run()
