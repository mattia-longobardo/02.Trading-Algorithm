"use client";

import * as React from "react";
import { CoinsIcon, KeyRoundIcon, ShieldAlertIcon, ShieldCheckIcon } from "lucide-react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { Stamp } from "@/components/stamp";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  MobileField,
  MobileFields,
  MobileItem,
  MobileItemHeader,
  MobileList,
} from "@/components/mobile-list";
import { CardSkeleton, ErrorState, TableSkeleton } from "@/components/query-states";
import { SearchableSelect } from "@/components/ui/searchable-select";
import type { SearchableOption } from "@/components/ui/searchable-select";
import {
  useFxRates,
  useSettings,
  useSettingsAudit,
  useAccountCredentials,
  useUpdateCredentials,
  useUpdateSettings,
  usePortfolio,
} from "@/lib/queries";
import { fmtNum } from "@/lib/format";
import { useDisplay } from "@/lib/money";
import { timeZoneOptions } from "@/lib/timezones";
import type { AppSettings, RiskLimits, SettingsUpdate } from "@/lib/types";

/** L'orario di run è UTC: qui si mostra a cosa corrisponde nel fuso scelto. */
function utcTimeInZone(schedule: string, zone: string): string | null {
  const [hh, mm] = schedule.split(":").map(Number);
  if (!Number.isInteger(hh) || !Number.isInteger(mm)) return null;
  const now = new Date();
  const at = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hh, mm),
  );
  try {
    return at.toLocaleTimeString("it-IT", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: zone,
    });
  } catch {
    return null;
  }
}

function fmtAuditValue(v: unknown): string {
  if (v == null) return "—";
  const value = typeof v === "string" ? v : JSON.stringify(v);
  return value.replaceAll("VOGLIO ANDARE LIVE", "Conferma esplicita legacy");
}

function SwitchesCard({ settings }: { settings: AppSettings }) {
  const update = useUpdateSettings();
  const [pending, setPending] = React.useState<SettingsUpdate | null>(null);

  const requestChange = (change: SettingsUpdate, dangerous: boolean) => {
    if (dangerous) {
      setPending(change);
    } else {
      update.mutate(change);
    }
  };

  const confirmPending = () => {
    if (!pending) return;
    update.mutate({ ...pending, confirmation: true });
    setPending(null);
  };

  const pendingLabel = "passare all'ambiente REALE";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ambiente</CardTitle>
        <CardDescription>
          Il passaggio verso demo è sempre permesso; verso reale servono
          conferma esplicita e guardrail lato backend
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <Label htmlFor="switch-environment" className="text-sm font-medium">
              Ambiente: {settings.environment === "real" ? "REALE" : "Demo"}
            </Label>
            <p className="text-muted-foreground text-xs">
              Demo usa il prefisso di esecuzione demo di eToro; reale muove
              denaro vero. Gli ordini approvati dal risk gate vengono sempre
              eseguiti per davvero nell&apos;ambiente scelto.
            </p>
          </div>
          <Switch
            id="switch-environment"
            checked={settings.environment === "real"}
            disabled={update.isPending}
            onCheckedChange={(checked) =>
              requestChange(
                { environment: checked ? "real" : "demo" },
                checked,
              )
            }
          />
        </div>

        {settings.live_ack && (
          <div className="rounded-md border p-3 text-sm">
            <p className="flex items-center gap-2 font-medium">
              <ShieldCheckIcon className="text-muted-foreground size-4" />
              Ultimo passaggio a reale
            </p>
            <p className="text-muted-foreground mt-1 text-xs">
              Conferma esplicita registrata dal backend
            </p>
          </div>
        )}
      </CardContent>

      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPending(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <ShieldAlertIcon className="text-negative size-5" />
              Conferma richiesta
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                <p>
                  Stai per {pendingLabel}. Il backend rifiuterà la richiesta
                  (422) senza la conferma esplicita.
                </p>
                <p>Conferma solo se vuoi permettere al bot di inviare ordini con denaro reale usando le tue chiavi eToro.</p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annulla</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={update.isPending}
              onClick={confirmPending}
            >
              Conferma
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

function ScheduleCard({ settings }: { settings: AppSettings }) {
  const update = useUpdateSettings();
  const [schedule, setSchedule] = React.useState(settings.schedule_utc);
  const [timezone, setTimezone] = React.useState(settings.timezone);
  const [weekdaysOnly, setWeekdaysOnly] = React.useState(settings.weekdays_only);

  // ~450 fusi: la lista si costruisce una volta sola dal database tz del browser.
  const zones = React.useMemo(() => timeZoneOptions(), []);
  const localEquivalent = utcTimeInZone(schedule, timezone);
  const validSchedule = /^([01]\d|2[0-3]):[0-5]\d$/.test(schedule);

  const dirty =
    schedule !== settings.schedule_utc ||
    timezone !== settings.timezone ||
    weekdaysOnly !== settings.weekdays_only;

  const save = () => {
    update.mutate({
      schedule_utc: schedule,
      timezone,
      weekdays_only: weekdaysOnly,
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Schedule</CardTitle>
        <CardDescription>
          L&apos;esecuzione è sempre in UTC: non si sposta con l&apos;ora legale.
          Il fuso qui sotto cambia solo come gli orari vengono mostrati
          nell&apos;app.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-1.5">
          <Label htmlFor="schedule-utc">
            Orario run (HH:MM){" "}
            <span className="text-muted-foreground font-mono text-[10px] tracking-[0.14em] uppercase">
              UTC
            </span>
          </Label>
          <Input
            id="schedule-utc"
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            placeholder="08:30"
            inputMode="numeric"
            aria-invalid={!validSchedule}
            className="font-mono tabular-nums"
          />
          <p className="text-muted-foreground text-xs">
            {validSchedule && localEquivalent ? (
              <>
                Corrisponde alle{" "}
                <span className="text-foreground font-mono tabular-nums">
                  {localEquivalent}
                </span>{" "}
                di {timezone.replace(/_/g, " ")}
              </>
            ) : (
              "Formato richiesto: HH:MM (24 ore)"
            )}
          </p>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="timezone">Fuso orario di visualizzazione</Label>
          <SearchableSelect
            id="timezone"
            value={timezone}
            onValueChange={setTimezone}
            options={zones}
            placeholder="Seleziona un fuso"
            searchPlaceholder="Cerca fuso o città…"
            emptyText="Nessun fuso trovato"
          />
        </div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <Label htmlFor="weekdays-only" className="text-sm font-medium">
              Solo giorni feriali
            </Label>
            <p className="text-muted-foreground text-xs">Run lun–ven (giorni UTC)</p>
          </div>
          <Switch
            id="weekdays-only"
            checked={weekdaysOnly}
            onCheckedChange={setWeekdaysOnly}
          />
        </div>
        <Button disabled={!dirty || !validSchedule || update.isPending} onClick={save}>
          {update.isPending ? "Salvataggio…" : "Salva"}
        </Button>
      </CardContent>
    </Card>
  );
}

function CurrencyCard({ settings }: { settings: AppSettings }) {
  const update = useUpdateSettings();
  const fx = useFxRates();
  const [currency, setCurrency] = React.useState(settings.currency);

  const options: SearchableOption[] = React.useMemo(() => {
    const rates = fx.data?.rates ?? {};
    const currencies = fx.data?.currencies ?? [{ code: "USD", label: "Dollaro USA" }];
    return currencies.map((option) => ({
      value: option.code,
      label: `${option.code} — ${option.label}`,
      hint:
        option.code === "USD" || !rates[option.code]
          ? undefined
          : fmtNum(rates[option.code], 4),
      keywords: option.label,
    }));
  }, [fx.data]);

  const rate = currency === "USD" ? 1 : fx.data?.rates?.[currency];
  const dirty = currency !== settings.currency;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CoinsIcon className="text-muted-foreground size-4" />
          Valuta
        </CardTitle>
        <CardDescription>
          eToro opera in dollari: importi e storico restano registrati in USD e
          vengono convertiti solo per la visualizzazione, ai cambi BCE.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-1.5">
          <Label htmlFor="currency">Valuta di visualizzazione</Label>
          <SearchableSelect
            id="currency"
            value={currency}
            onValueChange={setCurrency}
            options={options}
            placeholder="Seleziona una valuta"
            searchPlaceholder="Cerca valuta…"
            emptyText="Nessuna valuta trovata"
            disabled={fx.isLoading}
          />
        </div>

        <div className="border-primary/30 bg-primary/5 rounded-md border p-3">
          <p className="text-muted-foreground font-mono text-[10px] tracking-[0.14em] uppercase">
            Cambio applicato
          </p>
          <p className="mt-1 font-mono text-xl font-semibold tabular-nums">
            {currency === "USD"
              ? "1 USD = 1 USD"
              : rate
                ? `1 USD = ${fmtNum(rate, 4)} ${currency}`
                : "n/d"}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            {fx.data?.fetched_at
              ? `Aggiornato il ${new Date(fx.data.fetched_at).toLocaleString("it-IT")}`
              : "Cambio non ancora recuperato"}
            {fx.data?.stale ? " — non aggiornato, importi mostrati in USD" : ""}
          </p>
        </div>

        <Button
          disabled={!dirty || update.isPending}
          onClick={() => update.mutate({ currency })}
        >
          {update.isPending ? "Salvataggio…" : "Salva valuta"}
        </Button>
      </CardContent>
    </Card>
  );
}

function KeysCard() {
  const account = useAccountCredentials();
  const update = useUpdateCredentials();
  const [etoroApiKey, setEtoroApiKey] = React.useState("");
  const [etoroUserKey, setEtoroUserKey] = React.useState("");
  const [openaiApiKey, setOpenaiApiKey] = React.useState("");

  const save = () => {
    const body: { etoro_api_key?: string; etoro_user_key?: string; openai_api_key?: string } = {};
    if (etoroApiKey) body.etoro_api_key = etoroApiKey;
    if (etoroUserKey) body.etoro_user_key = etoroUserKey;
    if (openaiApiKey) body.openai_api_key = openaiApiKey;
    update.mutate(body, { onSuccess: () => { setEtoroApiKey(""); setEtoroUserKey(""); setOpenaiApiKey(""); } });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRoundIcon className="text-muted-foreground size-4" />
          Chiavi API personali
        </CardTitle>
        <CardDescription>
          Credenziali personali cifrate sul server e associate al tuo account Authentik
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 text-sm">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">API eToro</span>
            {account.data?.etoro_api_key_configured ? (
              <Stamp tone="approved">Configurate</Stamp>
            ) : (
              <Stamp tone="rejected">Mancanti</Stamp>
            )}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">User eToro</span>
            {account.data?.etoro_user_key_configured ? <Stamp tone="approved">Configurata</Stamp> : <Stamp tone="rejected">Mancante</Stamp>}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">OpenAI</span>
            {account.data?.openai_api_key_configured ? (
              <Stamp tone="approved">Configurata</Stamp>
            ) : (
              <Stamp tone="rejected">Mancante</Stamp>
            )}
          </div>
        </div>
        <div className="grid gap-3">
          <div className="grid gap-1.5"><Label htmlFor="etoro-api-key">API key eToro</Label><Input id="etoro-api-key" type="password" autoComplete="off" value={etoroApiKey} onChange={(event) => setEtoroApiKey(event.target.value)} placeholder={account.data?.etoro_api_key_configured ? "Configurata — inserisci per sostituire" : "Inserisci API key"} /></div>
          <div className="grid gap-1.5"><Label htmlFor="etoro-user-key">User key eToro</Label><Input id="etoro-user-key" type="password" autoComplete="off" value={etoroUserKey} onChange={(event) => setEtoroUserKey(event.target.value)} placeholder={account.data?.etoro_user_key_configured ? "Configurata — inserisci per sostituire" : "Inserisci user key"} /></div>
          <div className="grid gap-1.5"><Label htmlFor="openai-api-key">API key OpenAI</Label><Input id="openai-api-key" type="password" autoComplete="off" value={openaiApiKey} onChange={(event) => setOpenaiApiKey(event.target.value)} placeholder={account.data?.openai_api_key_configured ? "Configurata — inserisci per sostituire" : "Inserisci API key"} /></div>
          <Button disabled={update.isPending || (!etoroApiKey && !etoroUserKey && !openaiApiKey)} onClick={save}>Salva chiavi personali</Button>
        </div>
      </CardContent>
    </Card>
  );
}

const riskFields: { key: keyof RiskLimits; label: string; suffix: string; step?: number }[] = [
  { key: "max_position_pct_equity", label: "Peso massimo singola posizione", suffix: "%", step: 0.5 },
  { key: "max_total_exposure_pct", label: "Esposizione totale massima", suffix: "%", step: 1 },
  { key: "max_sector_exposure_pct", label: "Esposizione massima per settore", suffix: "%", step: 1 },
  { key: "min_cash_buffer_pct", label: "Riserva minima di liquidità", suffix: "%", step: 1 },
  { key: "max_open_positions", label: "Posizioni aperte massime", suffix: "", step: 1 },
  { key: "max_orders_per_run", label: "Ordini massimi per run", suffix: "", step: 1 },
  { key: "max_orders_per_day", label: "Ordini massimi al giorno", suffix: "", step: 1 },
];

function RiskLimitsCard({ settings }: { settings: AppSettings }) {
  const update = useUpdateSettings();
  const portfolio = usePortfolio();
  const display = useDisplay();
  const [limits, setLimits] = React.useState<RiskLimits>(settings.risk_limits);
  const dirty = JSON.stringify(limits) !== JSON.stringify(settings.risk_limits);
  const derivedMax = portfolio.data?.cash_usd != null && limits.max_open_positions > 0
    ? portfolio.data.cash_usd / limits.max_open_positions : null;
  return (
    <Card>
      <CardHeader><CardTitle>Limiti di rischio</CardTitle><CardDescription>Guardrail applicati dal backend prima di ogni ordine</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {riskFields.map((field) => <div key={field.key} className="grid gap-1.5"><Label htmlFor={`risk-${field.key}`}>{field.label}</Label><div className="relative"><Input id={`risk-${field.key}`} type="number" min={field.key.startsWith("max_orders") || field.key === "max_open_positions" ? 1 : 0} max={field.suffix === "%" ? 100 : undefined} step={field.step} value={limits[field.key]} onChange={(event) => setLimits((current) => ({ ...current, [field.key]: Number(event.target.value) }))} className={field.suffix ? "pr-8" : undefined} />{field.suffix ? <span className="text-muted-foreground pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs">{field.suffix}</span> : null}</div></div>)}
        </div>
        <div className="border-primary/30 bg-primary/5 rounded-md border p-3">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">Quantità massima per trade</p>
          <p className="mt-1 font-mono text-xl font-semibold tabular-nums">{display.money(derivedMax)}</p>
          <p className="text-muted-foreground mt-1 text-xs">Equity disponibile eToro ÷ {limits.max_open_positions} posizioni massime</p>
        </div>
        <Button disabled={!dirty || update.isPending} onClick={() => update.mutate({ risk_limits: limits })}>{update.isPending ? "Salvataggio…" : "Salva limiti"}</Button>
      </CardContent>
    </Card>
  );
}

function AuditCard() {
  const { data, isLoading, error } = useSettingsAudit();
  const display = useDisplay();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit log</CardTitle>
        <CardDescription>
          Ogni cambio di impostazioni è registrato con valore precedente e nuovo
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <TableSkeleton rows={5} />
        ) : error || !data ? (
          <ErrorState error={error} />
        ) : data.entries.length === 0 ? (
          <p className="text-muted-foreground py-8 text-center text-sm">
            Nessuna modifica registrata
          </p>
        ) : (
          <>
          <div className="max-md:hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Data</TableHead>
                <TableHead>Chiave</TableHead>
                <TableHead>Da</TableHead>
                <TableHead>A</TableHead>
                <TableHead>Origine</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.entries.map((e) => (
                <TableRow key={String(e.id)}>
                  <TableCell className="font-mono text-[13px] whitespace-nowrap tabular-nums">
                    {display.dateTime(e.changed_at)}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{e.key}</TableCell>
                  <TableCell className="text-muted-foreground max-w-48 truncate font-mono text-xs">
                    {fmtAuditValue(e.old_value)}
                  </TableCell>
                  <TableCell className="max-w-48 truncate font-mono text-xs">
                    {fmtAuditValue(e.new_value)}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {e.source}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
          <MobileList>
            {data.entries.map((e) => (
              <MobileItem key={String(e.id)}>
                <MobileItemHeader>
                  <span className="font-mono text-xs font-medium">{e.key}</span>
                  <span className="text-muted-foreground text-xs">{e.source}</span>
                </MobileItemHeader>
                <MobileFields>
                  <MobileField label="Da">
                    <span className="text-muted-foreground font-mono text-xs break-all">
                      {fmtAuditValue(e.old_value)}
                    </span>
                  </MobileField>
                  <MobileField label="A">
                    <span className="font-mono text-xs break-all">
                      {fmtAuditValue(e.new_value)}
                    </span>
                  </MobileField>
                  <MobileField label="Data" wide>
                    <span className="font-mono text-xs tabular-nums">
                      {display.dateTime(e.changed_at)}
                    </span>
                  </MobileField>
                </MobileFields>
              </MobileItem>
            ))}
          </MobileList>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { data: settings, isLoading, error } = useSettings();
  const portfolio = usePortfolio();
  const display = useDisplay();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Configurazione"
        title="Impostazioni"
        description={
          <>
            Persistite in app_settings su Postgres. Default sicuro: ambiente
            demo. Capitale disponibile rilevato direttamente da eToro:{" "}
            <span className="text-foreground font-mono tabular-nums">
              {display.money(portfolio.data?.cash_usd)}
            </span>
          </>
        }
      />

      {isLoading ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <CardSkeleton className="h-80 w-full" />
          <CardSkeleton className="h-80 w-full" />
        </div>
      ) : error || !settings ? (
        <ErrorState error={error} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <SwitchesCard settings={settings} />
          {/* key = valori server: il form si riallinea quando cambiano lato backend */}
          <ScheduleCard
            key={`${settings.schedule_utc}|${settings.timezone}|${settings.weekdays_only}`}
            settings={settings}
          />
          <CurrencyCard key={settings.currency} settings={settings} />
          <KeysCard />
          <RiskLimitsCard key={JSON.stringify(settings.risk_limits)} settings={settings} />
          <AuditCard />
        </div>
      )}
    </div>
  );
}
