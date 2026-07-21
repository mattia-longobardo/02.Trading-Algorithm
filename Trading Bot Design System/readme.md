# Trading Bot — Design System

Design system della dashboard di **Trading Bot**, un bot di swing trading multi-agente. Concetto: **"registro di borsa in pieno giorno"** — un pannello strumenti finanziario minimale e di precisione svizzera: la calma di un estratto conto stampato bene, non l'adrenalina di un terminale di trading. Ogni stato è un verdetto, e ogni verdetto è un **timbro da registro** (componente Stamp, la firma del sistema).

**Fonte:** specifica testuale auto-contenuta fornita dall'utente (nessun codebase, Figma o asset binari). Nessun logo fornito → il marchio si rende in tipografia pura (wordmark mono uppercase "TRADING BOT"); non disegnare mai un logo.

Personalità: sobrio, esatto, affidabile. Mai giocoso, mai drammatico. Tema light di default; dark come variante coerente (`.dark` sul root).

## Principi
1. **Un solo accent** — cobalto `#2440B3` solo per interattivo/attivo. Tutto il resto è inchiostro, grigio, bianco.
2. **Il colore ha semantica finanziaria** — verde = profitto, rosso = perdita/pericolo, ambra = cautela. Mai decorazione.
3. **I numeri sono sacri** — sempre Geist Mono + `tabular-nums`, right-aligned nelle tabelle.
4. **Hairline, non ombre** — struttura da bordi 1px; ombra massima `--shadow-xs` sulle card.
5. **Lo stato è un timbro** — ogni condizione passa dal componente Stamp, mai testo libero colorato.
6. **Motion quasi assente** — 150ms su hover/focus e basta; `prefers-reduced-motion` rispettato.

## CONTENT FUNDAMENTALS
- **Lingua**: italiano. **Casing**: sentence case ovunque tranne i dispositivi mono (eyebrow, header colonna, timbri, wordmark) che sono UPPERCASE.
- **Verbi attivi, bottoni che dicono cosa fanno**: "Esegui run ora", "Avvia dry-run" — mai "Invia" o "OK".
- **Numeri con unità e contesto**: sempre USD / %, e il numero di osservazioni accanto alle metriche statistiche ("Sharpe 1.31 · 42 trade").
- **Incalcolabile = "n/d"**, mai zero fittizio. Sotto 30 trade chiusi: "Campione insufficiente per conclusioni statistiche."
- **Stati vuoti = invito all'azione**: "Nessuna run ancora — avvia la prima dalla Dashboard."
- **Errori concreti**: cosa è successo e come rimediare; dettaglio dal backend, mai generici, senza scuse.
- **Niente emoji, mai.** Niente punti esclamativi entusiasti. Tono da estratto conto.

## VISUAL FOUNDATIONS
- **Colore**: sfondo `#FAFAF8` (bianco caldo appena grigio, mai cream); superfici `#FFFFFF`; inchiostro `#17181A`. Accent unico cobalto `#2440B3` (nav attiva, link, bottone primario, focus ring, serie equity). Semantici "da stampa", mai saturi: positive `#0F7B4D`, negative `#C2372E`, caution `#A66A00`, risk-high `#B4530F`. Il cobalto NON si usa mai per successo/errore. Badge ambiente: DEMO = cobalto, REALE = rosso (+ banner rosso persistente con `environment=real`). Palette grafici `--chart-1..5` in famiglia fredda vivace guidata dal cobalto (teal, indaco, smeraldo, magenta-rosa): tinte sature e nette ma di marca; distinzione rinforzata da tratteggio + legenda.
- **Tipografia**: tre voci — Newsreader 500 (SOLO h1 di pagina + claim corsivo), Instrument Sans (tutta la UI), Geist Mono `tabular-nums` (ogni cifra, timestamp, eyebrow, header colonna, timbro). Scala in `tokens/typography.css`.
- **Spazio**: multipli di 4px; padding card 24px; gap 16–24px; contenuto max ~1200px.
- **Forma**: radius piatti 3/4/6/8px — niente pill. Timbri a 3px.
- **Bordi & elevazione**: hairline 1px `--border` ovunque (card, tabelle, divisori); unica ombra `--shadow-xs`. Niente gradienti, glassmorphism, ombre morbide.
- **Sfondi**: piatti, nessuna immagine, texture o pattern.
- **Motion**: transizioni 150ms solo su hover/focus; zero animazioni d'ingresso/decorative; `prefers-reduced-motion` azzera tutto.
- **Hover**: righe tabella → `--muted`; ghost → `--accent`; link → opacity .8. Press: nessuno scale.
- **Focus**: ring cobalto 2px visibile su ogni interattivo.
- **Tabelle "estratto conto"**: solo hairline orizzontali, niente zebra/bordi verticali; header mono 11px uppercase muted; numeri mono right-aligned; stati via Stamp; PnL colorato solo sul valore.
- **Data viz**: griglia solo orizzontale hairline; assi mono 11px; equity bot in cobalto 1.5px, SPY `--benchmark` tratteggiato, SPY cash-flow `--benchmark-alt` dash corto (colore + tratteggio + legenda, mai solo colore); niente aree sfumate/gradienti/glow; tooltip = card bianca hairline con valori mono; heatmap divergente negative→bianco→positive via alpha 8→42%; gauge risk con fasce positive/caution/risk-high/negative.

## ICONOGRAPHY
- **Lucide** da CDN (`lucide` UMD), `strokeWidth: 1.5`, dimensione tipica 16–18px, colore corrente. Nessun icon font proprietario, nessun SVG custom, nessuna emoji, nessun carattere unicode come icona. Le frecce testuali "→" nei link "Tutte →" sono l'unica eccezione tipografica.
- Nessun logo fornito: wordmark testuale mono uppercase. **Intentional additions**: nessuna oltre a quanto in specifica.

## Fonts
Nessun file font fornito. Sostituzione: le tre famiglie esatte (Newsreader, Instrument Sans, Geist Mono) sono caricate da Google Fonts in `tokens/fonts.css`. Se esistono binari proprietari, sostituire con `@font-face` locali.

## Indice
- `styles.css` → importa `tokens/{fonts,colors,typography,spacing}.css`
- `guidelines/` — specimen card (colori, tipo, spazio, data viz)
- `components/core/` — Stamp, DotIndicator, Eyebrow
- `components/forms/` — Button, Input, Select, Checkbox, Switch
- `components/surfaces/` — Card, Dialog, Toast, Skeleton, Table (stili + esempio)
- `components/navigation/` — AppHeader, SidebarNav
- `ui_kits/dashboard/` — dashboard Trading Bot (index.html interattiva)
- `SKILL.md` — invocazione come Agent Skill
