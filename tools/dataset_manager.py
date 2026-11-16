"""
datasetmanager.py
Запуск без аргументов:
  - Камера, ПРОБЕЛ – начать/остановить запись
  - После остановки записи – сразу режим покадровой разметки
  - Скелет строго совпадает с видео, т.к. данные не пересохраняются на диск
  - S сохраняет CSV в папку data/datasets/
  - ESC – выход
Дополнительно: при старте можно нажать L, чтобы загрузить существующее видео и разметить.
"""

import cv2
import mediapipe as mp
import numpy as np
import pickle
import os
import time
from tkinter import Tk, filedialog

# ------------------------------
# Конфигурация классов и клавиш
# ------------------------------
CLASSES = {
    **{i: chr(i) for i in range(224, 256) if chr(i) != 'ё'},  # 32 русские буквы
    49: '1', 50: '2', 51: '3', 52: '4', 53: '5',
    76: 'Like',      # L
    68: 'Dislike',   # D
    32: 'None'       # пробел
}
CLASS_NAMES = {code: name for code, name in CLASSES.items()}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils

# ------------------------------
# DatasetManager – единый класс
# ------------------------------
class DatasetManager:
    def __init__(self):
        self.detector = mp_hands.Hands(
            static_image_mode=False,
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.cap = None
        self.recording = False

        # Для разметки
        self.frames = []          # кадры (изображения)
        self.landmarks = []       # landmarks (список или None)
        self.total_frames = 0
        self.current_idx = 0
        self.labels = []
        self.auto_advance = True

        # Папки
        self.record_dir = os.path.join(ROOT, "data", "records")
        os.makedirs(self.record_dir, exist_ok=True)
        self.dataset_dir = os.path.join(ROOT, "data", "datasets")
        os.makedirs(self.dataset_dir, exist_ok=True)

    # ----------------------------------------------------------------------
    # Основной цикл
    # ----------------------------------------------------------------------
    def run(self):
        """Главное меню/запись."""
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("Не удалось открыть камеру")
            return

        print("Жду действий:")
        print("  ПРОБЕЛ – записать новое видео и разметить")
        print("  L – загрузить существующее видео для разметки")
        print("  ESC – выход")

        while True:
            ret, frame = self.cap.read()
            if not ret:
                break
            display = frame.copy()
            cv2.putText(display, "SPACE: record new | L: load existing | ESC: quit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
            cv2.imshow("Dataset Manager", display)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                break
            elif key == 32:  # Пробел – начать запись
                self.record_and_label()
            elif key == ord('l') or key == ord('L'):
                self.load_and_label()

        self.cap.release()
        cv2.destroyAllWindows()

    # ----------------------------------------------------------------------
    # Запись + сразу разметка (без рассинхрона)
    # ----------------------------------------------------------------------
    def record_and_label(self):
        """Запись: копим кадры и landmarks в память, потом сразу разметка."""
        print("Нажмите ПРОБЕЛ, чтобы начать запись...")
        recording_started = False
        self.frames = []
        self.landmarks = []

        while True:
            ret, frame = self.cap.read()
            if not ret:
                break

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.detector.process(rgb)
            multi_hand = results.multi_hand_landmarks

            # Сохраняем в память (исходный кадр и landmarks)
            if recording_started:
                self.frames.append(frame.copy())
                self.landmarks.append(multi_hand)

            # Отображение
            display = frame.copy()
            if multi_hand:
                for hand_lms in multi_hand:
                    mp_drawing.draw_landmarks(display, hand_lms, mp_hands.HAND_CONNECTIONS)
            if recording_started:
                cv2.putText(display, "REC", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 3)

            cv2.imshow("Dataset Manager", display)
            key = cv2.waitKey(1) & 0xFF
            if key == 32:  # Пробел
                if not recording_started:
                    recording_started = True
                    print("Запись началась! Покажите жесты. ПРОБЕЛ – стоп.")
                else:
                    print("Запись остановлена.")
                    break
            if key == 27:  # ESC отменяет запись
                print("Запись отменена.")
                return

        # Сохраняем в файлы (опционально, чтобы потом можно было загрузить)
        self._save_record_to_disk()

        # Запускаем разметку с этими же данными
        self.total_frames = len(self.frames)
        self.labels = [None] * self.total_frames
        self.current_idx = 0
        self.label_loop()

    def _save_record_to_disk(self):
        """Сохраняет записанное видео и landmarks на диск (для архива)."""
        if not self.frames:
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        video_path = os.path.join(self.record_dir, f"record_{ts}.avi")
        pkl_path = os.path.join(self.record_dir, f"record_{ts}_landmarks.pkl")

        h, w = self.frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        writer = cv2.VideoWriter(video_path, fourcc, 30.0, (w, h))
        for f in self.frames:
            writer.write(f)
        writer.release()
        with open(pkl_path, 'wb') as f:
            pickle.dump(self.landmarks, f)
        print(f"Архив сохранён: {video_path} и {pkl_path}")

    # ----------------------------------------------------------------------
    # Загрузка существующего видео (если нужно)
    # ----------------------------------------------------------------------
    def load_and_label(self):
        """Диалог выбора файлов для разметки."""
        Tk().withdraw()
        video_path = filedialog.askopenfilename(
            title="Выберите видео AVI",
            filetypes=[("AVI files", "*.avi"), ("All files", "*.*")]
        )
        if not video_path:
            return
        base = os.path.splitext(video_path)[0]
        pkl_path = base + "_landmarks.pkl"
        if not os.path.exists(pkl_path):
            pkl_path = filedialog.askopenfilename(
                title="Выберите файл landmarks (.pkl)",
                filetypes=[("Pickle files", "*.pkl"), ("All files", "*.*")]
            )
            if not pkl_path:
                print("Не выбран файл landmarks, отмена.")
                return

        # Загружаем landmarks
        with open(pkl_path, 'rb') as f:
            self.landmarks = pickle.load(f)

        # Загружаем видео
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print("Не могу открыть видео для разметки")
            return
        self.frames = []
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            self.frames.append(frame)
        cap.release()

        # Синхронизируем длины
        min_len = min(len(self.frames), len(self.landmarks))
        self.frames = self.frames[:min_len]
        self.landmarks = self.landmarks[:min_len]
        self.total_frames = len(self.frames)
        self.labels = [None] * self.total_frames
        self.current_idx = 0

        self.label_loop()

    # ----------------------------------------------------------------------
    # Цикл разметки
    # ----------------------------------------------------------------------
    def label_loop(self):
        print("Разметка запущена.")
        print("← → — навигация, буквы/цифры/L/D/ПРОБЕЛ — метка, S — сохранить CSV, ESC — выход")

        cv2.namedWindow("Labeling", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Labeling", 1200, 700)

        while True:
            self.show_label_frame()
            key = cv2.waitKey(0) & 0xFF
            if key == 27:  # ESC
                break
            elif key == ord('s') or key == ord('S'):
                self.save_dataset()
                print("Датасет сохранён.")
            elif key == 81:  # стрелка влево
                self.current_idx = max(0, self.current_idx - 1)
            elif key == 83:  # стрелка вправо
                self.current_idx = min(self.total_frames - 1, self.current_idx + 1)
            elif key in CLASSES:
                self.labels[self.current_idx] = key
                if self.auto_advance and self.current_idx < self.total_frames - 1:
                    self.current_idx += 1
        cv2.destroyWindow("Labeling")

    # ----------------------------------------------------------------------
    # Отрисовка окна разметки
    # ----------------------------------------------------------------------
    def show_label_frame(self):
        canvas = np.zeros((700, 1200, 3), dtype=np.uint8)

        # Текущий кадр
        cur_frame = self.frames[self.current_idx].copy()
        cur_lm = self.landmarks[self.current_idx]
        if cur_lm:
            for hand_lms in cur_lm:
                mp_drawing.draw_landmarks(cur_frame, hand_lms, mp_hands.HAND_CONNECTIONS)

        label_code = self.labels[self.current_idx]
        label_text = CLASS_NAMES.get(label_code, "?") if label_code is not None else "—"
        cv2.rectangle(cur_frame, (0, 0), (cur_frame.shape[1], 40), (50,50,50), -1)
        cv2.putText(cur_frame, f"Frame: {self.current_idx}/{self.total_frames-1}  Label: {label_text}",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)

        top_area = canvas[0:550, 0:1200]
        top_area[:] = cv2.resize(cur_frame, (1200, 550))

        # Полоса предыдущих 5 кадров
        bottom_area = canvas[550:700, 0:1200]
        bottom_area[:] = (40,40,40)

        prev_indices = [self.current_idx - i for i in range(1, 6) if self.current_idx - i >= 0]
        prev_indices.reverse()

        small_w, small_h = 220, 140
        gap = 10
        total_width = len(prev_indices) * (small_w + gap) - gap
        start_x = (1200 - total_width) // 2

        for i, idx in enumerate(prev_indices):
            frame_small = self.frames[idx].copy()
            lm = self.landmarks[idx]
            if lm:
                h, w = frame_small.shape[:2]
                for hand_lms in lm:
                    for pt in hand_lms.landmark:
                        cx, cy = int(pt.x * w), int(pt.y * h)
                        cv2.circle(frame_small, (cx, cy), 3, (0,255,0), -1)
                    for conn in mp_hands.HAND_CONNECTIONS:
                        x0, y0 = int(hand_lms.landmark[conn[0]].x * w), int(hand_lms.landmark[conn[0]].y * h)
                        x1, y1 = int(hand_lms.landmark[conn[1]].x * w), int(hand_lms.landmark[conn[1]].y * h)
                        cv2.line(frame_small, (x0, y0), (x1, y1), (0,255,0), 1)

            lbl_code = self.labels[idx]
            lbl_text = CLASS_NAMES.get(lbl_code, "") if lbl_code is not None else ""
            cv2.putText(frame_small, f"t-{self.current_idx - idx}", (2,12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
            if lbl_text:
                cv2.putText(frame_small, lbl_text, (2,28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
            resized = cv2.resize(frame_small, (small_w, small_h))
            x = start_x + i * (small_w + gap)
            bottom_area[5:5+small_h, x:x+small_w] = resized

        cv2.imshow("Labeling", canvas)

    # ----------------------------------------------------------------------
    # Сохранение датасета в CSV (6-кадровые окна)
    # ----------------------------------------------------------------------
    def save_dataset(self):
        """Сохраняет окна 6 кадров для всех размеченных позиций."""
        if not self.frames:
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(self.dataset_dir, f"dataset_{ts}.csv")
        with open(csv_path, 'w') as f:
            header = "Target," + ",".join([f"f{i}" for i in range(378)]) + "\n"
            f.write(header)
            for t in range(5, self.total_frames):
                label_code = self.labels[t]
                if label_code is None:
                    continue
                features = []
                for offset in range(5, -1, -1):
                    lm_list = self.landmarks[t - offset]
                    if lm_list is None:
                        features.extend([0.0] * 63)
                    else:
                        hand_lms = lm_list[0]
                        for lm in hand_lms.landmark:
                            features.extend([lm.x, lm.y, lm.z])
                line = str(label_code) + "," + ",".join([str(v) for v in features]) + "\n"
                f.write(line)
        print(f"Датасет сохранён: {csv_path}")

# ------------------------------
# Запуск
# ------------------------------
if __name__ == "__main__":
    dm = DatasetManager()
    dm.run()