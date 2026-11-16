# data/

Здесь живут данные для обучения дактиля. В репозиторий они **не входят**: видеозаписи рук
весят сотни мегабайт и содержат личное видео, а CSV-окна легко воспроизвести.

```
data/
  datasets/   CSV с окнами по 6 кадров: 21 точка кисти + метка класса (то, на чём учится модель)
  records/    видео (*.avi), покадровые точки (*.pkl) и разметка (*.json) каждой записи
  samples/    короткие демо-ролики для проверки конвейера (--video)
```

Как получить свои данные:

```bash
python tools/dataset_manager.py            # записать и разметить: S сохраняет CSV в data/datasets/
python training/analyze_dataset.py         # распределение классов
python training/train_fingerspelling.py    # CV-отчёт и экспорт модели в handpilot/assets/models/
```

Подробнее о том, как мерить качество честно (leave-one-recording-out), смотрите в
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#дактиль).
