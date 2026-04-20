from __future__ import annotations


PROMPT_MODIFIERS: dict[str, str] = {
    "nh": 'Liefere NUR 3 alternative Titel-Vorschläge als JSON {"variants": ["t1","t2","t3"]}. Keine Paragraphen.',
    "sh": "Kürze den Entwurf auf ca. 60% der bisherigen Länge. Titel bleibt, Paragraphen werden straffer.",
    "lg": "Erweitere den Entwurf um Kontext und Hintergrund auf ca. 140% der bisherigen Länge. Keine Halluzinationen.",
    "fc": "Schreibe nüchtern und sachlich, ohne Wertungen, ohne Ausrufezeichen, im Agenturstil.",
    "em": "Schreibe mit mehr Spannung und erzählerischem Zug, aber ohne Clickbait. Keine Ausrufezeichen-Inflation.",
    "rg": "Schreibe den Entwurf komplett neu. Nutze andere Struktur, andere Headline und einen anderen Einstieg.",
}
