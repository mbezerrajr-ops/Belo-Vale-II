import { useEffect, useState, type ReactNode } from "react";
import { listFarms, setActiveFarmId, workspaceRequest } from "../../api/client";
import { ApiError, type Farm, type CurrentUser } from "../../api/types";
import { apiMessage } from "../../auth/AccountEntry";
import { setFarmTimezone } from "../../ui/dates";
import { FarmContext } from "./context";

interface Account { id: string; name: string; role: string }
interface Props { token: string; user: CurrentUser; onLogout: () => void; children: (user: CurrentUser, farmKey: string, farm: Farm) => ReactNode }

export function Workspace({ token, user, onLogout, children }: Props): JSX.Element {
  const [farms, setFarms] = useState<Farm[] | null>(null);
  const [selected, setSelected] = useState<Farm | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [managing, setManaging] = useState(false);
  const [reload, setReload] = useState(0);
  const key = `belo-vale.workspaces:${user.id}`;

  useEffect(() => {
    let cancelled = false;
    const display = (items: Farm[]): void => {
      if (cancelled) return;
      setFarms(items);
      let current: string | null = null;
      try { current = localStorage.getItem(`${key}:selected`); } catch { /* Sem seleção persistida, usar a primeira fazenda autorizada. */ }
      const farm = items.find((item) => item.id === current) ?? items[0] ?? null;
      if (farm) { try { localStorage.setItem(`${key}:selected`, farm.id); } catch { /* A seleção continua válida nesta abertura. */ } }
      setActiveFarmId(farm?.id ?? null); setFarmTimezone(farm?.timezone ?? "America/Recife"); setSelected(farm);
    };
    void listFarms(token).then((items) => {
      if (cancelled) return;
      try { localStorage.setItem(key, JSON.stringify(items)); } catch { /* A fila ainda informa falhas de persistência. */ }
      setError(null); display(items);
    }).catch((caught) => {
      if (cancelled) return;
      // Só falha de conexão aceita a cópia local. Acesso recusado nunca usa cache.
      if (!(caught instanceof ApiError) || caught.status >= 500) {
        try { const cached = JSON.parse(localStorage.getItem(key) ?? "null"); if (Array.isArray(cached)) { display(cached); return; } } catch { /* Sem cópia utilizável. */ }
      }
      setError(apiMessage(caught)); setFarms([]); setSelected(null); setActiveFarmId(null);
    });
    void workspaceRequest<Account[]>("/producer-accounts", token).then((items) => { if (!cancelled) setAccounts(items); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [token, user.id, reload]);

  function selectFarm(id: string): void {
    const farm = farms?.find((item) => item.id === id);
    if (!farm) return;
    setActiveFarmId(farm.id); setFarmTimezone(farm.timezone ?? "America/Recife");
    try { localStorage.setItem(`${key}:selected`, farm.id); } catch { /* Válida para a sessão atual. */ }
    window.history.replaceState(null, "", "/"); setSelected(farm); setManaging(false);
  }
  if (farms === null) return <main className="shell"><p role="status">Carregando suas fazendas…</p><button onClick={onLogout}>Cancelar carregamento</button></main>;
  return <>
    <a className="skip-link" href="#conteudo">Pular para o conteúdo</a>
    <div className="workspace-bar">
      <label htmlFor="active-farm">Fazenda</label>
      <select id="active-farm" value={selected?.id ?? ""} onChange={(event) => selectFarm(event.target.value)}>
        {!selected && <option value="">Nenhuma fazenda disponível</option>}
        {farms.map((farm) => <option key={farm.id} value={farm.id}>{farm.name}</option>)}
      </select>
      <button type="button" className="link-btn" onClick={() => setManaging(!managing)}>{managing ? "Voltar ao trabalho" : "Fazendas e equipe"}</button>
      {!selected && <button type="button" className="link-btn" onClick={onLogout}>Sair</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    {(managing || !selected || new URLSearchParams(window.location.search).get("action") === "invite")
      ? <FarmManagement token={token} farm={selected} accounts={accounts} onChanged={() => { setManaging(false); setReload((value) => value + 1); }} />
      : <FarmContext.Provider value={selected}>{children({ ...user, role: selected.role ?? user.role }, `${user.id}:${selected.id}`, selected)}</FarmContext.Provider>}
  </>;
}

function FarmManagement({ token, farm, accounts, onChanged }: { token: string; farm: Farm | null; accounts: Account[]; onChanged: () => void }): JSX.Element {
  const [name, setName] = useState(farm?.name ?? "");
  const [timezone, setTimezone] = useState(farm?.timezone ?? "America/Recife");
  const [lots, setLots] = useState((farm?.lot_settings ?? []).map((lot) => `${lot.kind === "diet" ? "ordenha" : "manejo"}: ${lot.name}`).join("\n"));
  const [newName, setNewName] = useState("");
  const [producerName, setProducerName] = useState("");
  const [catalogue, setCatalogue] = useState("");
  const [cataloguePreview, setCataloguePreview] = useState<{ items: Array<{ line: number; brinco: string; name: string; status: string; reason: string | null }>; new: number; invalid: number } | null>(null);
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("operator");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invitations, setInvitations] = useState<Array<{ id: string; email: string; role: string }>>([]);
  const [ownerId, setOwnerId] = useState("");
  const [ownerPassword, setOwnerPassword] = useState("");
  const [team, setTeam] = useState<Array<{ id: string; email: string }>>([]);
  const [accountMembers, setAccountMembers] = useState<Array<{ id: string; email: string; role: string }>>([]);
  const [usage, setUsage] = useState<{ storage_bytes: number; storage_limit_bytes: number; readings_today: number; daily_reading_limit: number } | null>(null);
  useEffect(() => {
    if (farm?.role !== "admin") return;
    void workspaceRequest<typeof invitations>("/farms/current/invitations", token).then(setInvitations).catch(() => undefined);
    void workspaceRequest<{ items: typeof team }>("/users", token).then((result) => setTeam(result.items)).catch(() => undefined);
    if (farm.producer_account_id && accounts.some((account) => account.id === farm.producer_account_id)) void workspaceRequest<typeof usage>(`/producer-accounts/${farm.producer_account_id}/usage`, token).then(setUsage).catch(() => undefined);
    if (farm.producer_account_id && accounts.some((account) => account.id === farm.producer_account_id && account.role === "owner")) void workspaceRequest<typeof accountMembers>(`/producer-accounts/${farm.producer_account_id}/members`, token).then(setAccountMembers).catch(() => undefined);
  }, [token, farm?.id, farm?.role, accounts]);

  async function perform(action: () => Promise<unknown>, success: string, reload = false): Promise<void> {
    setBusy(true); setError(null); setMessage(null);
    try { await action(); setMessage(success); if (reload) onChanged(); }
    catch (caught) { setError(apiMessage(caught)); }
    finally { setBusy(false); }
  }
  const inviteQuery = new URLSearchParams(window.location.search);
  return <main id="conteudo" className="shell farm-management">
    <h1>Fazendas e equipe</h1>
    {inviteQuery.get("action") === "invite" && <section><h2>Convite recebido</h2><p>Aceite com a conta do e-mail que recebeu o convite.</p><button disabled={busy} onClick={() => void perform(async () => { await workspaceRequest("/invitations/accept", token, "POST", { token: inviteQuery.get("token") }); window.history.replaceState(null, "", "/"); }, "Convite aceito.", true)}>Aceitar convite</button></section>}
    {farm?.role === "admin" && <form onSubmit={(event) => { event.preventDefault(); void perform(() => workspaceRequest("/farms/current", token, "PATCH", { name, timezone, milk_price_per_liter: farm.milk_price_per_liter ?? null,
      lot_settings: lots.split("\n").filter((line) => line.trim()).map((line) => { const divider = line.indexOf(":"); return { kind: line.slice(0, divider).trim() === "ordenha" ? "diet" : "management", name: line.slice(divider + 1).trim() }; }) }), "Configuração salva.", true); }}>
      <h2>Configuração da fazenda</h2><label htmlFor="farm-name">Nome da fazenda</label><input id="farm-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} />
      <label htmlFor="farm-timezone">Fuso horário</label><select id="farm-timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)}>{["America/Recife", "America/Sao_Paulo", "America/Manaus", "America/Cuiaba", "America/Rio_Branco", "America/Belem", "America/Bahia", "America/Fortaleza"].map((value) => <option key={value}>{value}</option>)}</select>
      <label htmlFor="farm-lots">Lotes e grupos de manejo</label><textarea id="farm-lots" rows={6} value={lots} onChange={(e) => setLots(e.target.value)} placeholder={"ordenha: Lote principal\nmanejo: Bezerreiro"} /><p className="hint">Um por linha: ordenha: Nome ou manejo: Nome. Os registros históricos são preservados.</p>
      <button disabled={busy}>Salvar configuração</button>
    </form>}
    {accounts.length === 0 && <form onSubmit={(event) => { event.preventDefault(); void perform(() => workspaceRequest("/producer-accounts", token, "POST", { name: producerName }), "Conta produtora criada.", true); }}>
      <h2>Criar minha conta produtora</h2><label htmlFor="producer-name">Seu nome ou nome da empresa</label><input id="producer-name" value={producerName} onChange={(e) => setProducerName(e.target.value)} required maxLength={255} /><button disabled={busy}>Criar conta produtora</button>
    </form>}
    {accounts.length > 0 && <form onSubmit={(event) => { event.preventDefault(); void perform(() => workspaceRequest("/farms/new", token, "POST", { name: newName, producer_account_id: accountId || accounts[0].id, timezone: "America/Recife", lot_settings: [] }), "Fazenda criada.", true); }}>
      <h2>Adicionar fazenda</h2><label htmlFor="producer-account">Conta produtora</label><select id="producer-account" value={accountId || accounts[0].id} onChange={(e) => setAccountId(e.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select>
      <label htmlFor="new-farm-name">Nome da nova fazenda</label><input id="new-farm-name" value={newName} onChange={(e) => setNewName(e.target.value)} required maxLength={255} /><button disabled={busy}>Criar fazenda</button>
    </form>}
    {farm && ["admin", "reviewer"].includes(farm.role ?? "") && <form onSubmit={(event) => { event.preventDefault(); void perform(async () => { const preview = await workspaceRequest<NonNullable<typeof cataloguePreview>>("/animals/import/preview", token, "POST", { csv: catalogue }); setCataloguePreview(preview); }, "Prévia carregada. Confira as linhas antes de confirmar."); }}>
      <h2>Importar cadastro de animais</h2><p className="hint">Arquivo CSV com colunas brinco;nome;lote. Lote é opcional. Configure os lotes da fazenda antes de importar.</p><label htmlFor="catalogue-file">Arquivo de cadastro CSV</label><input id="catalogue-file" type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) { if (file.size > 5_000_000) { setError("O limite é de 5 MB."); return; } void file.text().then((text) => { setCatalogue(text); setCataloguePreview(null); }); } }} /><button disabled={busy || !catalogue}>Conferir cadastro</button>
      {cataloguePreview && <><p>{cataloguePreview.new} novos animais; {cataloguePreview.invalid} linhas inválidas. Os existentes serão preservados.</p><div className="catalogue-preview"><table><thead><tr><th>Linha</th><th>Brinco</th><th>Nome</th><th>Conferência</th></tr></thead><tbody>{cataloguePreview.items.map((row) => <tr key={row.line}><td>{row.line}</td><td>{row.brinco}</td><td>{row.name}</td><td>{row.reason ?? "Novo cadastro"}</td></tr>)}</tbody></table></div><button type="button" disabled={busy || cataloguePreview.invalid > 0 || cataloguePreview.new === 0} onClick={() => void perform(async () => { await workspaceRequest("/animals/import", token, "POST", { csv: catalogue }); setCataloguePreview(null); setCatalogue(""); }, "Animais cadastrados.")}>Confirmar importação do cadastro</button></>}
    </form>}
    {farm?.role === "admin" && <form onSubmit={(event) => { event.preventDefault(); void perform(() => workspaceRequest("/farms/current/invitations", token, "POST", { email, role }), "Convite enviado por e-mail."); }}>
      <h2>Convidar integrante</h2><label htmlFor="invite-email">E-mail do integrante</label><input id="invite-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /><label htmlFor="invite-role">Permissão nesta fazenda</label><select id="invite-role" value={role} onChange={(e) => setRole(e.target.value)}><option value="operator">Operador</option><option value="reviewer">Revisor</option><option value="admin">Administrador</option></select><button disabled={busy}>Enviar convite</button>
      {invitations.map((invitation) => <p key={invitation.id}>{invitation.email} — {invitation.role} <button type="button" className="link-btn" disabled={busy} onClick={() => void perform(async () => { await workspaceRequest(`/farms/current/invitations/${invitation.id}`, token, "DELETE"); setInvitations((current) => current.filter((item) => item.id !== invitation.id)); }, "Convite cancelado.")}>Cancelar convite</button></p>)}
    </form>}
    {accounts.some((account) => account.id === farm?.producer_account_id && account.role === "owner") && <form onSubmit={(event) => { event.preventDefault(); void perform(() => workspaceRequest(`/producer-accounts/${farm?.producer_account_id}/transfer`, token, "POST", { user_id: ownerId, current_password: ownerPassword }), "Responsabilidade transferida.", true); }}>
      <h2>Transferir responsabilidade da conta produtora</h2><label htmlFor="new-owner">Novo responsável</label><select id="new-owner" required value={ownerId} onChange={(e) => setOwnerId(e.target.value)}><option value="">Escolha alguém da equipe</option>{team.map((member) => <option key={member.id} value={member.id}>{member.email}</option>)}</select><label htmlFor="owner-password">Sua senha atual</label><input id="owner-password" type="password" autoComplete="current-password" required value={ownerPassword} onChange={(e) => setOwnerPassword(e.target.value)} /><button disabled={busy}>Transferir responsabilidade</button>
    </form>}
    {accountMembers.filter((member) => member.role === "admin").map((member) => <p key={member.id}>Administrador da conta produtora: {member.email} <button type="button" className="link-btn" disabled={busy} onClick={() => {
      if (window.confirm(`Remover o acesso de ${member.email} às fazendas desta conta produtora?`)) void perform(() => workspaceRequest(`/producer-accounts/${farm?.producer_account_id}/members/${member.id}`, token, "DELETE"), "Acesso removido.", true);
    }}>Remover administrador da conta produtora</button></p>)}
    {usage && <p>Armazenamento: {(usage.storage_bytes / 1_000_000).toFixed(1)} de {(usage.storage_limit_bytes / 1_000_000).toFixed(0)} MB. Leituras hoje (UTC): {usage.readings_today} de {usage.daily_reading_limit}.</p>}
    {!farm && <p>Crie sua primeira fazenda ou aceite um convite para começar.</p>}
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
  </main>;
}
