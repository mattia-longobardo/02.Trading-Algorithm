const { Stamp, Button, Input, Dialog, Toast, AppHeader, SidebarNav, Switch } = window.EToroBotDesignSystem_9cb9fa;

function App() {
  const [page, setPage] = React.useState('dash');
  const [dark, setDark] = React.useState(false);
  const [env, setEnv] = React.useState('demo');
  const [killed, setKilled] = React.useState(false);
  const [dialog, setDialog] = React.useState(null); // 'kill' | 'golive'
  const [liveText, setLiveText] = React.useState('');
  const [toasts, setToasts] = React.useState([]);

  React.useEffect(() => { document.documentElement.classList.toggle('dark', dark); }, [dark]);
  const toast = (title, description, tone) => {
    const id = Date.now();
    setToasts((t) => [...t, { id, title, description, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  };

  const items = [
    { id: 'dash', label: 'Dashboard', icon: <Icon name="LayoutDashboard" /> },
    { id: 'dec', label: 'Decisioni', icon: <Icon name="Stamp" /> },
    { id: 'runs', label: 'Run', icon: <Icon name="History" /> },
    { id: 'risk', label: 'Rischio', icon: <Icon name="ShieldAlert" /> },
  ];

  return (
    <div style={{ display: 'flex', minHeight: '100%', background: 'var(--background)', color: 'var(--foreground)' }}>
      <SidebarNav style={{ position: 'sticky', top: 0, height: '100vh' }} items={items} activeId={page} onSelect={setPage} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <AppHeader environment={env} mode={env === 'real' ? 'live' : 'dry-run'}
          killSwitch={killed ? 'triggered' : 'ok'} breaker="ok" nextRun="2026-07-21 09:30"
          right={<Switch checked={dark} onChange={setDark} label="Scuro" />} />
        <main style={{ maxWidth: 1200, margin: '0 auto', padding: 24 }}>
          {page === 'dash' && <DashboardScreen toast={toast} onRunNow={() => toast('Run avviata', 'Prossimo aggiornamento tra circa 2 minuti.', 'success')} />}
          {page === 'dec' && <DecisionsScreen />}
          {page === 'runs' && <EmptyRunsScreen />}
          {page === 'risk' && <RiskScreen env={env} killed={killed} onKill={() => setDialog('kill')} onGoLive={() => { setLiveText(''); setDialog('golive'); }} />}
        </main>
      </div>

      <Dialog open={dialog === 'kill'} onClose={() => setDialog(null)}
        title="Attivare il kill switch?"
        description="Tutte le posizioni aperte verranno chiuse a mercato e il bot si fermerà. L'operazione non è annullabile."
        footer={<React.Fragment>
          <Button onClick={() => setDialog(null)}>Annulla</Button>
          <Button variant="destructive" onClick={() => { setKilled(true); setDialog(null); toast('Kill switch attivato', '3 posizioni chiuse a mercato. Il bot è fermo.', 'error'); }}>Attiva kill switch</Button>
        </React.Fragment>} />

      <Dialog open={dialog === 'golive'} onClose={() => setDialog(null)}
        title="Passare al conto reale?"
        description={'Gli ordini muoveranno denaro vero. Digita esattamente "VOGLIO ANDARE LIVE" per abilitare la conferma.'}
        footer={<React.Fragment>
          <Button onClick={() => setDialog(null)}>Annulla</Button>
          <Button variant="destructive" disabled={liveText !== 'VOGLIO ANDARE LIVE'}
            onClick={() => { setEnv('real'); setDialog(null); toast('Ambiente reale attivo', 'Il banner resterà visibile su ogni pagina.', 'error'); }}>Vai live</Button>
        </React.Fragment>}>
        <Input value={liveText} onChange={(e) => setLiveText(e.target.value)} placeholder="VOGLIO ANDARE LIVE" aria-label="Conferma go-live" />
      </Dialog>

      <div style={{ position: 'fixed', bottom: 16, right: 16, display: 'grid', gap: 8, zIndex: 60 }}>
        {toasts.map((t) => <Toast key={t.id} title={t.title} description={t.description} tone={t.tone} />)}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);