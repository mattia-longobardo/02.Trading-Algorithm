/* @ds-bundle: {"format":4,"namespace":"EToroBotDesignSystem_9cb9fa","components":[{"name":"DotIndicator","sourcePath":"components/core/DotIndicator.jsx"},{"name":"Eyebrow","sourcePath":"components/core/Eyebrow.jsx"},{"name":"Stamp","sourcePath":"components/core/Stamp.jsx"},{"name":"Button","sourcePath":"components/forms/Button.jsx"},{"name":"Checkbox","sourcePath":"components/forms/Checkbox.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Select","sourcePath":"components/forms/Select.jsx"},{"name":"Switch","sourcePath":"components/forms/Switch.jsx"},{"name":"AppHeader","sourcePath":"components/navigation/AppHeader.jsx"},{"name":"SidebarNav","sourcePath":"components/navigation/SidebarNav.jsx"},{"name":"Card","sourcePath":"components/surfaces/Card.jsx"},{"name":"Dialog","sourcePath":"components/surfaces/Dialog.jsx"},{"name":"Skeleton","sourcePath":"components/surfaces/Skeleton.jsx"},{"name":"Table","sourcePath":"components/surfaces/Table.jsx"},{"name":"Toast","sourcePath":"components/surfaces/Toast.jsx"}],"sourceHashes":{"components/core/DotIndicator.jsx":"ef6ffca27c32","components/core/Eyebrow.jsx":"4fa461c4ac09","components/core/Stamp.jsx":"d0aab82010e5","components/forms/Button.jsx":"138634504dae","components/forms/Checkbox.jsx":"220a463e39db","components/forms/Input.jsx":"b6cd070d8bee","components/forms/Select.jsx":"f9830c715f47","components/forms/Switch.jsx":"a4af31d7a30a","components/navigation/AppHeader.jsx":"db7a488d6b01","components/navigation/SidebarNav.jsx":"c5a9e7c62fa0","components/surfaces/Card.jsx":"1ab81d195c6c","components/surfaces/Dialog.jsx":"b91ddc94664d","components/surfaces/Skeleton.jsx":"03db214c14e9","components/surfaces/Table.jsx":"7992c55d6ed8","components/surfaces/Toast.jsx":"078a4688799b","ui_kits/dashboard/app.jsx":"de60359df9a3","ui_kits/dashboard/charts.jsx":"c8a244a4006f","ui_kits/dashboard/screens.jsx":"7e6061a387e9"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.EToroBotDesignSystem_9cb9fa = window.EToroBotDesignSystem_9cb9fa || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/DotIndicator.jsx
try { (() => {
function DotIndicator({
  status = 'ok',
  label,
  style
}) {
  const color = status === 'ok' ? 'var(--positive)' : 'var(--negative)';
  return /*#__PURE__*/React.createElement("span", {
    className: "ds-dot",
    style: style
  }, /*#__PURE__*/React.createElement("span", {
    className: "ds-dot__dot",
    style: {
      background: color
    }
  }), label);
}
Object.assign(__ds_scope, { DotIndicator });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/DotIndicator.jsx", error: String((e && e.message) || e) }); }

// components/core/Eyebrow.jsx
try { (() => {
function Eyebrow({
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "ds-eyebrow",
    style: style
  }, children);
}
Object.assign(__ds_scope, { Eyebrow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Eyebrow.jsx", error: String((e && e.message) || e) }); }

// components/core/Stamp.jsx
try { (() => {
function Stamp({
  tone = 'neutral',
  children,
  style,
  className = ''
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: 'ds-stamp ds-stamp--' + tone + ' ' + className,
    style: style
  }, children);
}
Object.assign(__ds_scope, { Stamp });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Stamp.jsx", error: String((e && e.message) || e) }); }

// components/forms/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Button({
  variant = 'secondary',
  children,
  className = '',
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    className: 'ds-btn ds-btn--' + variant + ' ' + className
  }, rest), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Button.jsx", error: String((e && e.message) || e) }); }

// components/forms/Checkbox.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Checkbox({
  label,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("label", {
    className: "ds-checkbox"
  }, /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox"
  }, rest)), label);
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Input({
  label,
  id,
  className = '',
  ...rest
}) {
  const input = /*#__PURE__*/React.createElement("input", _extends({
    id: id,
    className: 'ds-input ' + className
  }, rest));
  if (!label) return input;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    className: "ds-label",
    htmlFor: id
  }, label), input);
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Select.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Select({
  label,
  id,
  options = [],
  className = '',
  ...rest
}) {
  const sel = /*#__PURE__*/React.createElement("select", _extends({
    id: id,
    className: 'ds-select ' + className
  }, rest), options.map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label)));
  if (!label) return sel;
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    className: "ds-label",
    htmlFor: id
  }, label), sel);
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Select.jsx", error: String((e && e.message) || e) }); }

// components/forms/Switch.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Switch({
  checked = false,
  onChange,
  label,
  ...rest
}) {
  const btn = /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    role: "switch",
    "aria-checked": checked,
    className: "ds-switch",
    onClick: () => onChange && onChange(!checked)
  }, rest));
  if (!label) return btn;
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 14,
      cursor: 'pointer'
    }
  }, btn, label);
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Switch.jsx", error: String((e && e.message) || e) }); }

// components/navigation/AppHeader.jsx
try { (() => {
function AppHeader({
  environment = 'demo',
  mode = 'dry-run',
  killSwitch = 'ok',
  breaker = 'ok',
  nextRun,
  left,
  right
}) {
  const real = environment === 'real';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 40
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "ds-header",
    style: {
      position: 'static'
    }
  }, left, /*#__PURE__*/React.createElement(__ds_scope.Stamp, {
    tone: real ? 'solid-danger' : 'accent'
  }, real ? 'Reale' : 'Demo'), /*#__PURE__*/React.createElement(__ds_scope.Stamp, {
    tone: mode === 'live' ? 'caution' : 'neutral'
  }, mode === 'live' ? 'Live' : 'Dry-run'), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(__ds_scope.DotIndicator, {
    status: killSwitch === 'ok' ? 'ok' : 'triggered',
    label: "Kill switch"
  }), /*#__PURE__*/React.createElement(__ds_scope.DotIndicator, {
    status: breaker === 'ok' ? 'ok' : 'triggered',
    label: "Breaker"
  }), nextRun && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      letterSpacing: '.08em',
      textTransform: 'uppercase',
      color: 'var(--muted-foreground)',
      fontVariantNumeric: 'tabular-nums'
    }
  }, "Prossima run ", nextRun), right), real && /*#__PURE__*/React.createElement("div", {
    className: "ds-banner-real"
  }, "Conto reale \u2014 gli ordini muovono denaro vero"));
}
Object.assign(__ds_scope, { AppHeader });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/AppHeader.jsx", error: String((e && e.message) || e) }); }

// components/navigation/SidebarNav.jsx
try { (() => {
function SidebarNav({
  items = [],
  activeId,
  onSelect,
  style
}) {
  return /*#__PURE__*/React.createElement("nav", {
    className: "ds-sidebar",
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 16px 12px',
      borderBottom: '1px solid var(--border)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontWeight: 500,
      fontSize: 14,
      letterSpacing: '.08em',
      textTransform: 'uppercase'
    }
  }, "Trading Bot"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 10,
      letterSpacing: '.18em',
      textTransform: 'uppercase',
      color: 'var(--muted-foreground)',
      marginTop: 2
    }
  }, "Swing trading")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 0',
      flex: 1
    }
  }, items.map(it => /*#__PURE__*/React.createElement("a", {
    key: it.id,
    href: "#",
    onClick: e => {
      e.preventDefault();
      onSelect && onSelect(it.id);
    },
    className: 'ds-sidebar__item' + (it.id === activeId ? ' ds-sidebar__item--active' : '')
  }, it.icon, it.label))));
}
Object.assign(__ds_scope, { SidebarNav });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/SidebarNav.jsx", error: String((e && e.message) || e) }); }

// components/surfaces/Card.jsx
try { (() => {
function Card({
  title,
  description,
  action,
  children,
  style,
  className = '',
  bodyStyle
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: 'ds-card ' + className,
    style: style
  }, (title || action) && /*#__PURE__*/React.createElement("div", {
    className: "ds-card__header"
  }, /*#__PURE__*/React.createElement("div", null, title && /*#__PURE__*/React.createElement("div", {
    className: "ds-card__title"
  }, title), description && /*#__PURE__*/React.createElement("div", {
    className: "ds-card__desc"
  }, description)), action), /*#__PURE__*/React.createElement("div", {
    className: "ds-card__body",
    style: bodyStyle
  }, children));
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/surfaces/Card.jsx", error: String((e && e.message) || e) }); }

// components/surfaces/Dialog.jsx
try { (() => {
function Dialog({
  open,
  title,
  description,
  children,
  footer,
  onClose
}) {
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "ds-dialog-overlay",
    onClick: e => {
      if (e.target === e.currentTarget && onClose) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "ds-dialog",
    role: "alertdialog",
    "aria-modal": "true"
  }, title && /*#__PURE__*/React.createElement("div", {
    className: "ds-card__title"
  }, title), description && /*#__PURE__*/React.createElement("div", {
    className: "ds-card__desc",
    style: {
      marginTop: 4
    }
  }, description), children && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, children), footer && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 20,
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 8
    }
  }, footer)));
}
Object.assign(__ds_scope, { Dialog });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/surfaces/Dialog.jsx", error: String((e && e.message) || e) }); }

// components/surfaces/Skeleton.jsx
try { (() => {
function Skeleton({
  width = '100%',
  height = 14,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "ds-skeleton",
    style: {
      width,
      height,
      ...style
    }
  });
}
Object.assign(__ds_scope, { Skeleton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/surfaces/Skeleton.jsx", error: String((e && e.message) || e) }); }

// components/surfaces/Table.jsx
try { (() => {
function Table({
  columns = [],
  rows = [],
  rowKey,
  style
}) {
  return /*#__PURE__*/React.createElement("table", {
    className: "ds-table",
    style: style
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, columns.map(c => /*#__PURE__*/React.createElement("th", {
    key: c.key,
    className: c.align === 'right' ? 'num' : ''
  }, c.label)))), /*#__PURE__*/React.createElement("tbody", null, rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: rowKey ? r[rowKey] : i
  }, columns.map(c => /*#__PURE__*/React.createElement("td", {
    key: c.key,
    className: c.align === 'right' ? 'num' : ''
  }, r[c.key]))))));
}
Object.assign(__ds_scope, { Table });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/surfaces/Table.jsx", error: String((e && e.message) || e) }); }

// components/surfaces/Toast.jsx
try { (() => {
function Toast({
  title,
  description,
  tone = 'neutral',
  style
}) {
  const c = tone === 'error' ? 'var(--negative)' : tone === 'success' ? 'var(--positive)' : 'var(--foreground)';
  return /*#__PURE__*/React.createElement("div", {
    className: "ds-toast",
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 600,
      color: c
    }
  }, title), description && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)'
    }
  }, description));
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/surfaces/Toast.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/app.jsx
try { (() => {
const {
  Stamp,
  Button,
  Input,
  Dialog,
  Toast,
  AppHeader,
  SidebarNav,
  Switch
} = window.EToroBotDesignSystem_9cb9fa;
function App() {
  const [page, setPage] = React.useState('dash');
  const [dark, setDark] = React.useState(false);
  const [env, setEnv] = React.useState('demo');
  const [killed, setKilled] = React.useState(false);
  const [dialog, setDialog] = React.useState(null); // 'kill' | 'golive'
  const [liveText, setLiveText] = React.useState('');
  const [toasts, setToasts] = React.useState([]);
  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);
  const toast = (title, description, tone) => {
    const id = Date.now();
    setToasts(t => [...t, {
      id,
      title,
      description,
      tone
    }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4200);
  };
  const items = [{
    id: 'dash',
    label: 'Dashboard',
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "LayoutDashboard"
    })
  }, {
    id: 'dec',
    label: 'Decisioni',
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "Stamp"
    })
  }, {
    id: 'runs',
    label: 'Run',
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "History"
    })
  }, {
    id: 'risk',
    label: 'Rischio',
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "ShieldAlert"
    })
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      minHeight: '100%',
      background: 'var(--background)',
      color: 'var(--foreground)'
    }
  }, /*#__PURE__*/React.createElement(SidebarNav, {
    style: {
      position: 'sticky',
      top: 0,
      height: '100vh'
    },
    items: items,
    activeId: page,
    onSelect: setPage
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement(AppHeader, {
    environment: env,
    mode: env === 'real' ? 'live' : 'dry-run',
    killSwitch: killed ? 'triggered' : 'ok',
    breaker: "ok",
    nextRun: "2026-07-21 09:30",
    right: /*#__PURE__*/React.createElement(Switch, {
      checked: dark,
      onChange: setDark,
      label: "Scuro"
    })
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      maxWidth: 1200,
      margin: '0 auto',
      padding: 24
    }
  }, page === 'dash' && /*#__PURE__*/React.createElement(DashboardScreen, {
    toast: toast,
    onRunNow: () => toast('Run avviata', 'Prossimo aggiornamento tra circa 2 minuti.', 'success')
  }), page === 'dec' && /*#__PURE__*/React.createElement(DecisionsScreen, null), page === 'runs' && /*#__PURE__*/React.createElement(EmptyRunsScreen, null), page === 'risk' && /*#__PURE__*/React.createElement(RiskScreen, {
    env: env,
    killed: killed,
    onKill: () => setDialog('kill'),
    onGoLive: () => {
      setLiveText('');
      setDialog('golive');
    }
  }))), /*#__PURE__*/React.createElement(Dialog, {
    open: dialog === 'kill',
    onClose: () => setDialog(null),
    title: "Attivare il kill switch?",
    description: "Tutte le posizioni aperte verranno chiuse a mercato e il bot si fermer\xE0. L'operazione non \xE8 annullabile.",
    footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
      onClick: () => setDialog(null)
    }, "Annulla"), /*#__PURE__*/React.createElement(Button, {
      variant: "destructive",
      onClick: () => {
        setKilled(true);
        setDialog(null);
        toast('Kill switch attivato', '3 posizioni chiuse a mercato. Il bot è fermo.', 'error');
      }
    }, "Attiva kill switch"))
  }), /*#__PURE__*/React.createElement(Dialog, {
    open: dialog === 'golive',
    onClose: () => setDialog(null),
    title: "Passare al conto reale?",
    description: 'Gli ordini muoveranno denaro vero. Digita esattamente "VOGLIO ANDARE LIVE" per abilitare la conferma.',
    footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
      onClick: () => setDialog(null)
    }, "Annulla"), /*#__PURE__*/React.createElement(Button, {
      variant: "destructive",
      disabled: liveText !== 'VOGLIO ANDARE LIVE',
      onClick: () => {
        setEnv('real');
        setDialog(null);
        toast('Ambiente reale attivo', 'Il banner resterà visibile su ogni pagina.', 'error');
      }
    }, "Vai live"))
  }, /*#__PURE__*/React.createElement(Input, {
    value: liveText,
    onChange: e => setLiveText(e.target.value),
    placeholder: "VOGLIO ANDARE LIVE",
    "aria-label": "Conferma go-live"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      bottom: 16,
      right: 16,
      display: 'grid',
      gap: 8,
      zIndex: 60
    }
  }, toasts.map(t => /*#__PURE__*/React.createElement(Toast, {
    key: t.id,
    title: t.title,
    description: t.description,
    tone: t.tone
  }))));
}
ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(App, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/app.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/charts.jsx
try { (() => {
const {
  Card
} = window.EToroBotDesignSystem_9cb9fa;
function Icon({
  name,
  size = 16
}) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current || !window.lucide) return;
    ref.current.innerHTML = '';
    const el = window.lucide.createElement(window.lucide[name]);
    el.setAttribute('width', size);
    el.setAttribute('height', size);
    el.setAttribute('stroke-width', '1.5');
    ref.current.appendChild(el);
  }, [name, size]);
  return /*#__PURE__*/React.createElement("span", {
    ref: ref,
    style: {
      display: 'inline-flex',
      width: size,
      height: size,
      flex: 'none'
    }
  });
}
function EquityChart({
  height = 220
}) {
  // serie fittizie: bot, SPY lump-sum, SPY cash-flow matched
  const W = 920,
    H = height,
    pad = {
      l: 56,
      r: 12,
      t: 10,
      b: 24
    };
  const n = 40;
  const mk = (drift, vol, seed) => {
    let v = 10000,
      out = [];
    for (let i = 0; i < n; i++) {
      v *= 1 + drift + vol * Math.sin(seed * 3 + i * 0.9) * (0.4 + i * seed * 7919 % 10 / 14);
      out.push(v);
    }
    return out;
  };
  const bot = mk(0.006, 0.008, 1.3),
    spy = mk(0.0035, 0.005, 2.1),
    spycf = mk(0.003, 0.004, 3.7);
  const all = [...bot, ...spy, ...spycf];
  const min = Math.min(...all) * 0.99,
    max = Math.max(...all) * 1.01;
  const x = i => pad.l + i / (n - 1) * (W - pad.l - pad.r);
  const y = v => pad.t + (1 - (v - min) / (max - min)) * (H - pad.t - pad.b);
  const path = s => s.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1)).join(' ');
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => min + f * (max - min));
  const fmt = v => (v / 1000).toFixed(1) + 'k';
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("svg", {
    viewBox: '0 0 ' + W + ' ' + H,
    style: {
      width: '100%',
      display: 'block'
    }
  }, ticks.map((t, i) => /*#__PURE__*/React.createElement("g", {
    key: i
  }, /*#__PURE__*/React.createElement("line", {
    x1: pad.l,
    x2: W - pad.r,
    y1: y(t),
    y2: y(t),
    stroke: "var(--border)"
  }), /*#__PURE__*/React.createElement("text", {
    x: pad.l - 8,
    y: y(t) + 3,
    textAnchor: "end",
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      fill: 'var(--muted-foreground)'
    }
  }, fmt(t)))), /*#__PURE__*/React.createElement("path", {
    d: path(spy),
    fill: "none",
    stroke: "var(--benchmark)",
    strokeWidth: "1.5",
    strokeDasharray: "6 4"
  }), /*#__PURE__*/React.createElement("path", {
    d: path(spycf),
    fill: "none",
    stroke: "var(--benchmark-alt)",
    strokeWidth: "1.5",
    strokeDasharray: "2 3"
  }), /*#__PURE__*/React.createElement("path", {
    d: path(bot),
    fill: "none",
    stroke: "var(--primary)",
    strokeWidth: "1.5"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      marginTop: 8,
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      textTransform: 'uppercase',
      letterSpacing: '.08em',
      color: 'var(--muted-foreground)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--primary)'
    }
  }, "\u2014 Bot"), /*#__PURE__*/React.createElement("span", null, "- - SPY lump-sum"), /*#__PURE__*/React.createElement("span", null, "\xB7\xB7 SPY cash-flow matched")));
}
function RiskGauge({
  value = 4
}) {
  const bands = [{
    to: 3,
    c: 'var(--positive)',
    l: 'basso'
  }, {
    to: 6,
    c: 'var(--caution)',
    l: 'medio'
  }, {
    to: 8,
    c: 'var(--risk-high)',
    l: 'alto'
  }, {
    to: 10,
    c: 'var(--negative)',
    l: 'estremo'
  }];
  const band = bands.find(b => value <= b.to);
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 2
    }
  }, Array.from({
    length: 10
  }, (_, i) => {
    const b = bands.find(bb => i + 1 <= bb.to);
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        flex: 1,
        height: 10,
        borderRadius: 2,
        background: i < value ? b.c : 'var(--muted)',
        border: '1px solid var(--border)'
      }
    });
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      marginTop: 8,
      alignItems: 'baseline'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontWeight: 600,
      fontSize: 22,
      fontVariantNumeric: 'tabular-nums'
    }
  }, value, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)'
    }
  }, "/10")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      textTransform: 'uppercase',
      letterSpacing: '.08em',
      color: band.c
    }
  }, band.l)));
}
function SectorDonut() {
  const data = [{
    l: 'Tech',
    v: 34,
    c: 'var(--chart-1)'
  }, {
    l: 'Energia',
    v: 22,
    c: 'var(--chart-2)'
  }, {
    l: 'Salute',
    v: 18,
    c: 'var(--chart-3)'
  }, {
    l: 'Finanza',
    v: 15,
    c: 'var(--chart-4)'
  }, {
    l: 'Altro',
    v: 11,
    c: 'var(--chart-5)'
  }];
  const R = 46,
    r = 30,
    C = 2 * Math.PI * ((R + r) / 2);
  let acc = 0;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "110",
    height: "110",
    viewBox: "0 0 110 110"
  }, data.map((d, i) => {
    const frac = d.v / 100,
      dash = frac * C;
    const el = /*#__PURE__*/React.createElement("circle", {
      key: i,
      cx: "55",
      cy: "55",
      r: (R + r) / 2,
      fill: "none",
      stroke: d.c,
      strokeWidth: R - r,
      strokeDasharray: dash - 2 + ' ' + (C - dash + 2),
      strokeDashoffset: -acc * C + C / 4
    });
    acc += frac;
    return el;
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gap: 4,
      flex: 1
    }
  }, data.map(d => /*#__PURE__*/React.createElement("div", {
    key: d.l,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      borderBottom: '1px solid var(--border)',
      paddingBottom: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      background: d.c,
      flex: 'none'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      flex: 1
    }
  }, d.l), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 13,
      fontVariantNumeric: 'tabular-nums'
    }
  }, d.v, "%")))));
}
function MonthlyHeatmap() {
  const months = ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug'];
  const vals = [1.8, -0.6, 3.2, 0.4, -1.9, 2.6, 1.1];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 2
    }
  }, months.map((m, i) => {
    const v = vals[i];
    const a = Math.min(42, 8 + Math.abs(v) * 10);
    const bg = v === 0 ? 'var(--card)' : 'color-mix(in srgb, var(--' + (v > 0 ? 'positive' : 'negative') + ') ' + a + '%, var(--card))';
    return /*#__PURE__*/React.createElement("div", {
      key: m,
      style: {
        flex: 1,
        border: '1px solid var(--border)',
        background: bg,
        padding: '8px 4px',
        textAlign: 'center'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: '.08em',
        color: 'var(--muted-foreground)'
      }
    }, m), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        fontVariantNumeric: 'tabular-nums',
        marginTop: 2
      }
    }, v > 0 ? '+' : v < 0 ? '−' : '', Math.abs(v).toFixed(1), "%"));
  }));
}
Object.assign(window, {
  Icon,
  EquityChart,
  RiskGauge,
  SectorDonut,
  MonthlyHeatmap
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/charts.jsx", error: String((e && e.message) || e) }); }

// ui_kits/dashboard/screens.jsx
try { (() => {
const {
  Stamp,
  Eyebrow,
  Button,
  Card,
  Table,
  Skeleton
} = window.EToroBotDesignSystem_9cb9fa;
const pnl = (v, unit = '') => v == null ? /*#__PURE__*/React.createElement("span", {
  style: {
    color: 'var(--muted-foreground)'
  }
}, "n/d") : /*#__PURE__*/React.createElement("span", {
  style: {
    color: v >= 0 ? 'var(--positive)' : 'var(--negative)'
  }
}, (v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString('it-IT', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
}) + unit);
function PageTitle({
  eyebrow,
  title,
  action
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 24
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, eyebrow), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 16,
      marginTop: 10
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 500,
      fontSize: 30,
      margin: 0
    }
  }, title), action));
}
function Metric({
  label,
  value,
  unit,
  sub
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontWeight: 500,
      fontSize: 11,
      textTransform: 'uppercase',
      letterSpacing: '.18em',
      color: 'var(--muted-foreground)'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontWeight: 600,
      fontSize: 22,
      fontVariantNumeric: 'tabular-nums',
      marginTop: 6,
      whiteSpace: 'nowrap'
    }
  }, value, unit && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 400,
      color: 'var(--muted-foreground)',
      marginLeft: 4
    }
  }, unit)), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)',
      marginTop: 2
    }
  }, sub));
}
function DashboardScreen({
  onRunNow,
  toast
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(PageTitle, {
    eyebrow: "Dashboard",
    title: "Stato del portafoglio",
    action: /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement(Button, {
      onClick: () => toast('Dry-run avviata', 'Nessun ordine verrà inviato al broker.')
    }, "Avvia dry-run"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      onClick: onRunNow
    }, "Esegui run ora"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement(Card, {
    bodyStyle: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement(Metric, {
    label: "Equity",
    value: "12.847,32",
    unit: "USD",
    sub: "Capitale iniziale 10.000 USD"
  })), /*#__PURE__*/React.createElement(Card, {
    bodyStyle: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement(Metric, {
    label: "PnL totale",
    value: pnl(2847.32),
    unit: "USD",
    sub: /*#__PURE__*/React.createElement("span", null, pnl(28.47, '%'), " dall'avvio")
  })), /*#__PURE__*/React.createElement(Card, {
    bodyStyle: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement(Metric, {
    label: "Sharpe",
    value: "1,31",
    sub: "42 trade chiusi"
  })), /*#__PURE__*/React.createElement(Card, {
    bodyStyle: {
      padding: 20
    }
  }, /*#__PURE__*/React.createElement(Metric, {
    label: "Max drawdown",
    value: pnl(-7.9, '%'),
    sub: "12 mar \u2013 4 apr 2026"
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '2fr 1fr',
      gap: 16,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Curva equity",
    description: "Bot vs SPY, da avvio (ott 2025)"
  }, /*#__PURE__*/React.createElement(EquityChart, null)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gap: 16,
      alignContent: 'start'
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Rendimenti mensili",
    bodyStyle: {
      paddingTop: 12
    }
  }, /*#__PURE__*/React.createElement(MonthlyHeatmap, null)), /*#__PURE__*/React.createElement(Card, {
    title: "Esposizione per settore",
    bodyStyle: {
      paddingTop: 12
    }
  }, /*#__PURE__*/React.createElement(SectorDonut, null)))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Run recenti",
    description: "Ultime 4 esecuzioni",
    action: /*#__PURE__*/React.createElement("a", {
      href: "#",
      onClick: e => e.preventDefault()
    }, "Tutte \u2192"),
    bodyStyle: {
      paddingTop: 8
    }
  }, /*#__PURE__*/React.createElement(Table, {
    columns: [{
      key: 'ts',
      label: 'Data / ora',
      align: 'right'
    }, {
      key: 'mode',
      label: 'Modalità'
    }, {
      key: 'prop',
      label: 'Proposte',
      align: 'right'
    }, {
      key: 'appr',
      label: 'Approvate',
      align: 'right'
    }, {
      key: 'esito',
      label: 'Esito'
    }],
    rows: [{
      ts: '2026-07-20 09:30',
      mode: /*#__PURE__*/React.createElement(Stamp, {
        tone: "caution"
      }, "Live"),
      prop: '5',
      appr: '3',
      esito: /*#__PURE__*/React.createElement(Stamp, {
        tone: "approved"
      }, "OK")
    }, {
      ts: '2026-07-17 09:30',
      mode: /*#__PURE__*/React.createElement(Stamp, {
        tone: "caution"
      }, "Live"),
      prop: '4',
      appr: '4',
      esito: /*#__PURE__*/React.createElement(Stamp, {
        tone: "approved"
      }, "OK")
    }, {
      ts: '2026-07-15 09:30',
      mode: /*#__PURE__*/React.createElement(Stamp, {
        tone: "neutral"
      }, "Dry-run"),
      prop: '6',
      appr: '2',
      esito: /*#__PURE__*/React.createElement(Stamp, {
        tone: "approved"
      }, "OK")
    }, {
      ts: '2026-07-13 09:30',
      mode: /*#__PURE__*/React.createElement(Stamp, {
        tone: "caution"
      }, "Live"),
      prop: '3',
      appr: '0',
      esito: /*#__PURE__*/React.createElement(Stamp, {
        tone: "rejected"
      }, "Failed")
    }]
  }))));
}
function DecisionsScreen() {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(PageTitle, {
    eyebrow: "Registro",
    title: "Registro delle decisioni"
  }), /*#__PURE__*/React.createElement(Card, {
    title: "Run del 2026-07-20 09:30",
    description: "L'LLM ha proposto 5 ordini; il codice ne ha approvati 3.",
    bodyStyle: {
      paddingTop: 8
    }
  }, /*#__PURE__*/React.createElement(Table, {
    columns: [{
      key: 't',
      label: 'Ticker'
    }, {
      key: 'az',
      label: 'Azione'
    }, {
      key: 'q',
      label: 'Qty',
      align: 'right'
    }, {
      key: 'px',
      label: 'Prezzo USD',
      align: 'right'
    }, {
      key: 'verd',
      label: 'Verdetto'
    }, {
      key: 'mot',
      label: 'Motivazione'
    }],
    rows: [{
      t: 'AAPL',
      az: 'Compra',
      q: '12',
      px: '227,90',
      verd: /*#__PURE__*/React.createElement(Stamp, {
        tone: "approved"
      }, "Approvato"),
      mot: /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13,
          color: 'var(--muted-foreground)'
        }
      }, "Entro i limiti di size e settore")
    }, {
      t: 'NVDA',
      az: 'Compra',
      q: '4',
      px: '1.204,50',
      verd: /*#__PURE__*/React.createElement(Stamp, {
        tone: "rejected"
      }, "Respinto"),
      mot: /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13,
          color: 'var(--muted-foreground)'
        }
      }, "Size oltre il 5% del portafoglio")
    }, {
      t: 'XOM',
      az: 'Vendi',
      q: '20',
      px: '118,32',
      verd: /*#__PURE__*/React.createElement(Stamp, {
        tone: "approved"
      }, "Approvato"),
      mot: /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13,
          color: 'var(--muted-foreground)'
        }
      }, "Stop-loss raggiunto")
    }, {
      t: 'MSFT',
      az: 'Compra',
      q: '6',
      px: '512,10',
      verd: /*#__PURE__*/React.createElement(Stamp, {
        tone: "rejected"
      }, "Respinto"),
      mot: /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13,
          color: 'var(--muted-foreground)'
        }
      }, "Correlazione eccessiva con AAPL")
    }, {
      t: 'JNJ',
      az: 'Compra',
      q: '10',
      px: '162,74',
      verd: /*#__PURE__*/React.createElement(Stamp, {
        tone: "approved"
      }, "Filled"),
      mot: /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13,
          color: 'var(--muted-foreground)'
        }
      }, "Entro tutti i vincoli")
    }]
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)',
      marginTop: 12
    }
  }, "Campione insufficiente per conclusioni statistiche (42 trade chiusi su 30 minimi raggiunti \u2014 metriche per-strategia n/d sotto soglia).")));
}
function RiskScreen({
  env,
  killed,
  onKill,
  onGoLive
}) {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(PageTitle, {
    eyebrow: "Sicurezza",
    title: "Rischio e controlli"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr 1fr',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Risk score",
    description: "Esposizione complessiva del portafoglio"
  }, /*#__PURE__*/React.createElement(RiskGauge, {
    value: 4
  })), /*#__PURE__*/React.createElement(Card, {
    title: "Circuit breaker",
    description: "Trip a \u22125% giornaliero"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)'
    }
  }, "Stato"), /*#__PURE__*/React.createElement(Stamp, {
    tone: "approved"
  }, "OK")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)'
    }
  }, "Perdita odierna"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 13,
      fontVariantNumeric: 'tabular-nums',
      color: 'var(--negative)'
    }
  }, "\u22121,20%")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)'
    }
  }, "Margine al trip"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 13,
      fontVariantNumeric: 'tabular-nums'
    }
  }, "3,80%")))), /*#__PURE__*/React.createElement(Card, {
    title: "Controlli",
    description: "Azioni irreversibili \u2014 richiedono conferma"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--muted-foreground)'
    }
  }, "Ambiente"), /*#__PURE__*/React.createElement(Stamp, {
    tone: env === 'real' ? 'solid-danger' : 'accent'
  }, env === 'real' ? 'Reale' : 'Demo')), env !== 'real' && /*#__PURE__*/React.createElement(Button, {
    onClick: onGoLive
  }, "Passa al conto reale"), /*#__PURE__*/React.createElement(Button, {
    variant: "destructive",
    onClick: onKill,
    disabled: killed
  }, killed ? 'Kill switch attivo' : 'Kill switch'), killed && /*#__PURE__*/React.createElement(Stamp, {
    tone: "solid-danger",
    style: {
      justifySelf: 'start'
    }
  }, "Kill switch attivo")))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Posizioni aperte",
    description: "7 posizioni \xB7 esposizione 68% del capitale",
    bodyStyle: {
      paddingTop: 8
    }
  }, /*#__PURE__*/React.createElement(Table, {
    columns: [{
      key: 't',
      label: 'Ticker'
    }, {
      key: 'q',
      label: 'Qty',
      align: 'right'
    }, {
      key: 'pm',
      label: 'Prezzo medio',
      align: 'right'
    }, {
      key: 'pa',
      label: 'Ultimo',
      align: 'right'
    }, {
      key: 'p',
      label: 'PnL USD',
      align: 'right'
    }, {
      key: 'pp',
      label: 'PnL %',
      align: 'right'
    }],
    rows: [{
      t: 'AAPL',
      q: '24',
      pm: '219,10',
      pa: '227,90',
      p: pnl(211.20),
      pp: pnl(4.01, '%')
    }, {
      t: 'JNJ',
      q: '10',
      pm: '162,74',
      pa: '161,90',
      p: pnl(-8.40),
      pp: pnl(-0.52, '%')
    }, {
      t: 'XLE',
      q: '18',
      pm: '96,20',
      pa: '101,45',
      p: pnl(94.50),
      pp: pnl(5.46, '%')
    }]
  }))));
}
function EmptyRunsScreen() {
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(PageTitle, {
    eyebrow: "Run",
    title: "Storico run"
  }), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: '32px 0'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14
    }
  }, "Nessuna run ancora \u2014 avvia la prima dalla Dashboard."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16,
      display: 'grid',
      gap: 8,
      maxWidth: 420,
      margin: '16px auto 0'
    }
  }, /*#__PURE__*/React.createElement(Skeleton, null), /*#__PURE__*/React.createElement(Skeleton, {
    width: "80%"
  }), /*#__PURE__*/React.createElement(Skeleton, {
    width: "60%"
  })))));
}
Object.assign(window, {
  DashboardScreen,
  DecisionsScreen,
  RiskScreen,
  EmptyRunsScreen,
  PageTitle
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/dashboard/screens.jsx", error: String((e && e.message) || e) }); }

__ds_ns.DotIndicator = __ds_scope.DotIndicator;

__ds_ns.Eyebrow = __ds_scope.Eyebrow;

__ds_ns.Stamp = __ds_scope.Stamp;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.AppHeader = __ds_scope.AppHeader;

__ds_ns.SidebarNav = __ds_scope.SidebarNav;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Dialog = __ds_scope.Dialog;

__ds_ns.Skeleton = __ds_scope.Skeleton;

__ds_ns.Table = __ds_scope.Table;

__ds_ns.Toast = __ds_scope.Toast;

})();
