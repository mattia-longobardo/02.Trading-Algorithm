Dialog di conferma: bordo hairline + ombra minima. Obbligatorio per ogni azione irreversibile (kill switch, go-live).

```jsx
<Dialog open={open} onClose={close} title="Attivare il kill switch?"
  description="Tutte le posizioni aperte verranno chiuse a mercato."
  footer={<><Button onClick={close}>Annulla</Button><Button variant="destructive" onClick={confirm}>Attiva kill switch</Button></>} />
```