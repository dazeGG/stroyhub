# Матчинг

Раздел **Матчинг** сейчас работает только в read-only режиме.

![Кандидаты матчинга](/help/screenshots/matches.png)

## Что показывает экран

- пары возможных дублей;
- confidence;
- метод матчинга;
- normalized title;
- token overlap;
- токены только слева и только справа.

## Важная граница

В M12 кандидат на экране не означает принятый матч. Accept/reject действия
специально отложены до полноценного persistence и review workflow.

## Как ревьюить

1. Начни с `95%+`.
2. Сравни названия, магазины, категории и normalized title.
3. Проверь overlap и left/right-only токены.
4. Записывай true positives и false positives в issue.

## Когда открывать issue

- false positive требует нового blocker для веса, размера, цвета, сорта или упаковки;
- true positives встречаются массово и пора делать persistence;
- нужен accept/reject workflow с audit fields.
