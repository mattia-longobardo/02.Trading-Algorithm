const { Stamp, Eyebrow, Button, Card, Table, Skeleton } = window.EToroBotDesignSystem_9cb9fa;

const pnl = (v, unit = '') => v == null
  ? <span style={{ color: 'var(--muted-foreground)' }}>n/d</span>
  : <span style={{ color: v >= 0 ? 'var(--positive)' : 'var(--negative)' }}>{(v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + unit}</span>;

function PageTitle({ eyebrow, title, action }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, marginTop: 10 }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontWeight: 500, fontSize: 30, margin: 0 }}>{title}</h1>
        {action}
      </div>
    </div>
  );
}

function Metric({ label, value, unit, sub }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.18em', color: 'var(--muted-foreground)' }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 22, fontVariantNumeric: 'tabular-nums', marginTop: 6, whiteSpace: 'nowrap' }}>{value}{unit && <span style={{ fontSize: 13, fontWeight: 400, color: 'var(--muted-foreground)', marginLeft: 4 }}>{unit}</span>}</div>
      {sub && <div style={{ fontSize: 13, color: 'var(--muted-foreground)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function DashboardScreen({ onRunNow, toast }) {
  return (
    <div>
      <PageTitle eyebrow="Dashboard" title="Stato del portafoglio" action={
        <div style={{ display: 'flex', gap: 8 }}>
          <Button onClick={() => toast('Dry-run avviata', 'Nessun ordine verrà inviato al broker.')}>Avvia dry-run</Button>
          <Button variant="primary" onClick={onRunNow}>Esegui run ora</Button>
        </div>} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
        <Card bodyStyle={{ padding: 20 }}><Metric label="Equity" value="12.847,32" unit="USD" sub="Capitale iniziale 10.000 USD" /></Card>
        <Card bodyStyle={{ padding: 20 }}><Metric label="PnL totale" value={pnl(2847.32)} unit="USD" sub={<span>{pnl(28.47, '%')} dall'avvio</span>} /></Card>
        <Card bodyStyle={{ padding: 20 }}><Metric label="Sharpe" value="1,31" sub="42 trade chiusi" /></Card>
        <Card bodyStyle={{ padding: 20 }}><Metric label="Max drawdown" value={pnl(-7.9, '%')} sub="12 mar – 4 apr 2026" /></Card>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, marginTop: 16 }}>
        <Card title="Curva equity" description="Bot vs SPY, da avvio (ott 2025)"><EquityChart /></Card>
        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <Card title="Rendimenti mensili" bodyStyle={{ paddingTop: 12 }}><MonthlyHeatmap /></Card>
          <Card title="Esposizione per settore" bodyStyle={{ paddingTop: 12 }}><SectorDonut /></Card>
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <Card title="Run recenti" description="Ultime 4 esecuzioni" action={<a href="#" onClick={(e) => e.preventDefault()}>Tutte →</a>} bodyStyle={{ paddingTop: 8 }}>
          <Table
            columns={[{ key: 'ts', label: 'Data / ora', align: 'right' }, { key: 'mode', label: 'Modalità' }, { key: 'prop', label: 'Proposte', align: 'right' }, { key: 'appr', label: 'Approvate', align: 'right' }, { key: 'esito', label: 'Esito' }]}
            rows={[
              { ts: '2026-07-20 09:30', mode: <Stamp tone="caution">Live</Stamp>, prop: '5', appr: '3', esito: <Stamp tone="approved">OK</Stamp> },
              { ts: '2026-07-17 09:30', mode: <Stamp tone="caution">Live</Stamp>, prop: '4', appr: '4', esito: <Stamp tone="approved">OK</Stamp> },
              { ts: '2026-07-15 09:30', mode: <Stamp tone="neutral">Dry-run</Stamp>, prop: '6', appr: '2', esito: <Stamp tone="approved">OK</Stamp> },
              { ts: '2026-07-13 09:30', mode: <Stamp tone="caution">Live</Stamp>, prop: '3', appr: '0', esito: <Stamp tone="rejected">Failed</Stamp> },
            ]} />
        </Card>
      </div>
    </div>
  );
}

function DecisionsScreen() {
  return (
    <div>
      <PageTitle eyebrow="Registro" title="Registro delle decisioni" />
      <Card title="Run del 2026-07-20 09:30" description="L'LLM ha proposto 5 ordini; il codice ne ha approvati 3." bodyStyle={{ paddingTop: 8 }}>
        <Table
          columns={[{ key: 't', label: 'Ticker' }, { key: 'az', label: 'Azione' }, { key: 'q', label: 'Qty', align: 'right' }, { key: 'px', label: 'Prezzo USD', align: 'right' }, { key: 'verd', label: 'Verdetto' }, { key: 'mot', label: 'Motivazione' }]}
          rows={[
            { t: 'AAPL', az: 'Compra', q: '12', px: '227,90', verd: <Stamp tone="approved">Approvato</Stamp>, mot: <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Entro i limiti di size e settore</span> },
            { t: 'NVDA', az: 'Compra', q: '4', px: '1.204,50', verd: <Stamp tone="rejected">Respinto</Stamp>, mot: <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Size oltre il 5% del portafoglio</span> },
            { t: 'XOM', az: 'Vendi', q: '20', px: '118,32', verd: <Stamp tone="approved">Approvato</Stamp>, mot: <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Stop-loss raggiunto</span> },
            { t: 'MSFT', az: 'Compra', q: '6', px: '512,10', verd: <Stamp tone="rejected">Respinto</Stamp>, mot: <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Correlazione eccessiva con AAPL</span> },
            { t: 'JNJ', az: 'Compra', q: '10', px: '162,74', verd: <Stamp tone="approved">Filled</Stamp>, mot: <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Entro tutti i vincoli</span> },
          ]} />
        <div style={{ fontSize: 13, color: 'var(--muted-foreground)', marginTop: 12 }}>Campione insufficiente per conclusioni statistiche (42 trade chiusi su 30 minimi raggiunti — metriche per-strategia n/d sotto soglia).</div>
      </Card>
    </div>
  );
}

function RiskScreen({ env, killed, onKill, onGoLive }) {
  return (
    <div>
      <PageTitle eyebrow="Sicurezza" title="Rischio e controlli" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
        <Card title="Risk score" description="Esposizione complessiva del portafoglio"><RiskGauge value={4} /></Card>
        <Card title="Circuit breaker" description="Trip a −5% giornaliero">
          <div style={{ display: 'grid', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Stato</span><Stamp tone="approved">OK</Stamp></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Perdita odierna</span><span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontVariantNumeric: 'tabular-nums', color: 'var(--negative)' }}>−1,20%</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Margine al trip</span><span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>3,80%</span></div>
          </div>
        </Card>
        <Card title="Controlli" description="Azioni irreversibili — richiedono conferma">
          <div style={{ display: 'grid', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'var(--muted-foreground)' }}>Ambiente</span>
              <Stamp tone={env === 'real' ? 'solid-danger' : 'accent'}>{env === 'real' ? 'Reale' : 'Demo'}</Stamp>
            </div>
            {env !== 'real' && <Button onClick={onGoLive}>Passa al conto reale</Button>}
            <Button variant="destructive" onClick={onKill} disabled={killed}>{killed ? 'Kill switch attivo' : 'Kill switch'}</Button>
            {killed && <Stamp tone="solid-danger" style={{ justifySelf: 'start' }}>Kill switch attivo</Stamp>}
          </div>
        </Card>
      </div>
      <div style={{ marginTop: 16 }}>
        <Card title="Posizioni aperte" description="7 posizioni · esposizione 68% del capitale" bodyStyle={{ paddingTop: 8 }}>
          <Table
            columns={[{ key: 't', label: 'Ticker' }, { key: 'q', label: 'Qty', align: 'right' }, { key: 'pm', label: 'Prezzo medio', align: 'right' }, { key: 'pa', label: 'Ultimo', align: 'right' }, { key: 'p', label: 'PnL USD', align: 'right' }, { key: 'pp', label: 'PnL %', align: 'right' }]}
            rows={[
              { t: 'AAPL', q: '24', pm: '219,10', pa: '227,90', p: pnl(211.20), pp: pnl(4.01, '%') },
              { t: 'JNJ', q: '10', pm: '162,74', pa: '161,90', p: pnl(-8.40), pp: pnl(-0.52, '%') },
              { t: 'XLE', q: '18', pm: '96,20', pa: '101,45', p: pnl(94.50), pp: pnl(5.46, '%') },
            ]} />
        </Card>
      </div>
    </div>
  );
}

function EmptyRunsScreen() {
  return (
    <div>
      <PageTitle eyebrow="Run" title="Storico run" />
      <Card>
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <div style={{ fontSize: 14 }}>Nessuna run ancora — avvia la prima dalla Dashboard.</div>
          <div style={{ marginTop: 16, display: 'grid', gap: 8, maxWidth: 420, margin: '16px auto 0' }}><Skeleton /><Skeleton width="80%" /><Skeleton width="60%" /></div>
        </div>
      </Card>
    </div>
  );
}

Object.assign(window, { DashboardScreen, DecisionsScreen, RiskScreen, EmptyRunsScreen, PageTitle });