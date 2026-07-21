Tabella estratto conto. Niente zebra, niente bordi verticali; PnL colorato solo sul valore.

```jsx
<Table columns={[{key:'t',label:'Ticker'},{key:'pnl',label:'PnL',align:'right'},{key:'st',label:'Esito'}]}
  rows={[{t:'AAPL', pnl:<span style={{color:'var(--positive)'}}>+312,40</span>, st:<Stamp tone="approved">Filled</Stamp>}]} />
```