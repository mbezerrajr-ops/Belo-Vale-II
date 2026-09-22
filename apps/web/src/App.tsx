import { useEffect, useState } from "react";

import {
  getAnimal,
  getCurrentFarm,
  getCurrentUser,
  getImportReview,
  listProposals,
  logout as endSession,
  refreshSession,
} from "./api/client";
import type {
  AnimalDetail,
  CurrentUser,
  Farm,
  ImportReview,
  UploadResult,
} from "./api/types";
import { LoginForm } from "./auth/LoginForm";
import { clearStoredToken, loadStoredToken, storeToken } from "./auth/session";
import { AnimalDetailPanel } from "./features/animals/AnimalDetailPanel";
import { AnimalSearchPage } from "./features/animals/AnimalSearchPage";
import { HerdDashboard } from "./features/dashboard/HerdDashboard";
import { OfficialMeasurements } from "./features/dashboard/OfficialMeasurements";
import { SuppliesPage } from "./features/dashboard/SuppliesPage";
import { ReviewWorkspace } from "./features/imports/ReviewWorkspace";
import { UploadForm } from "./features/imports/UploadForm";
import { ProductionPage } from "./features/production/ProductionPage";
import { ReviewInbox } from "./features/review/ReviewInbox";
import { ChangePasswordForm } from "./features/users/ChangePasswordForm";
import { UsersPage } from "./features/users/UsersPage";
import { Cows, Hills, Icons, LogoMark, type IconName } from "./ui/Brand";
import { PageHeader } from "./ui/PageHeader";
import { useRoute, type AreaRoute } from "./router";

type SessionState =
  | { status: "checking" }
  | { status: "signed-out" }
  | { status: "signed-in"; token: string; user: CurrentUser };

/** Quanto esperar o servidor encerrar a sessão antes de sair mesmo assim. */
const LOGOUT_WAIT_MS = 5_000;

export function App(): JSX.Element {
  const [session, setSession] = useState<SessionState>({ status: "checking" });

  useEffect(() => {
    let cancelled = false;

    // Tenta o token da aba; se não houver ou não valer mais, tenta renovar
    // pelo cookie de sessão. É o que evita pedir login de novo a quem apenas
    // reabriu o aplicativo no celular.
    async function restore(): Promise<void> {
      const storedToken = loadStoredToken();
      if (storedToken !== null) {
        try {
          const user = await getCurrentUser(storedToken);
          if (!cancelled) {
            setSession({ status: "signed-in", token: storedToken, user });
          }
          return;
        } catch {
          clearStoredToken();
        }
      }

      const renewed = await refreshSession().catch(() => null);
      if (renewed === null) {
        if (!cancelled) setSession({ status: "signed-out" });
        return;
      }
      try {
        const user = await getCurrentUser(renewed.access_token);
        storeToken(renewed.access_token);
        if (!cancelled) {
          setSession({ status: "signed-in", token: renewed.access_token, user });
        }
      } catch {
        if (!cancelled) setSession({ status: "signed-out" });
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  // Renova antes de vencer, para que ninguém seja desconectado no meio do
  // trabalho. O token de acesso continua curto; o que dura é o cookie.
  useEffect(() => {
    if (session.status !== "signed-in") return;

    const interval = window.setInterval(
      () => {
        void refreshSession()
          .then((renewed) => {
            if (renewed === null) {
              clearStoredToken();
              setSession({ status: "signed-out" });
              return;
            }
            storeToken(renewed.access_token);
            setSession((current) =>
              current.status === "signed-in"
                ? { ...current, token: renewed.access_token }
                : current,
            );
          })
          .catch(() => {
            // Falha de rede não desloga: a próxima tentativa resolve.
          });
      },
      10 * 60 * 1000,
    );

    return () => window.clearInterval(interval);
  }, [session.status]);

  const handleLoggedIn = async (loginResult: { access_token: string }): Promise<void> => {
    const token = loginResult.access_token;
    const user = await getCurrentUser(token);
    storeToken(token);
    setSession({ status: "signed-in", token, user });
  };

  const handleLogout = async (): Promise<void> => {
    // Revoga no servidor: apagar o token só do navegador deixaria a sessão
    // viva para quem tivesse o cookie. E *espera* a revogação antes de mostrar
    // o login: se a página recarregasse no meio, o pedido seria cortado e o
    // cookie ainda válido reabriria a sessão de quem acabou de sair.
    clearStoredToken();
    await Promise.race([
      endSession().catch(() => {
        // Sem resposta do servidor, o acesso local é encerrado mesmo assim.
      }),
      new Promise((resolve) => window.setTimeout(resolve, LOGOUT_WAIT_MS)),
    ]);
    // O próximo a entrar neste celular não abre na ficha que ficou na tela.
    window.history.replaceState(null, "", "/");
    setSession({ status: "signed-out" });
  };

  if (session.status === "checking") {
    return (
      // Enquanto confere a sessão: a marca, não um retângulo cinza — com rede
      // lenta no celular, o cinza parecia travado.
      <main className="splash" aria-busy="true">
        <span className="sr-only" role="status">
          Carregando
        </span>
        <LogoMark size={72} />
        <strong>Belo Vale II</strong>
        <span className="splash-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
      </main>
    );
  }

  // Senha provisória: até escolher uma nova, a conta só alcança a troca.
  // O servidor já barra o resto; esconder evita uma tela cheia de erros.
  if (session.status === "signed-in" && session.user.must_change_password) {
    const { token } = session;
    return (
      <main className="shell forced-password">
        <header className="topbar">
          <span className="wordmark">
            <LogoMark />
            <span>
              <strong>Belo Vale II</strong>
              <small>Gestão do rebanho leiteiro</small>
            </span>
          </span>
          <div className="who">
            <button type="button" className="link-btn" onClick={() => void handleLogout()}>
              <Icons.logout /> Sair
            </button>
          </div>
        </header>
        <section className="forced-password-card">
          <h2>Escolha uma senha nova</h2>
          <p className="muted">
            Sua senha foi redefinida pelo administrador. Use a senha provisória que
            você recebeu como "senha atual" e escolha uma senha só sua para continuar.
          </p>
          <ChangePasswordForm
            token={token}
            onChanged={() => {
              void getCurrentUser(token).then((user) =>
                setSession({ status: "signed-in", token, user }),
              );
            }}
          />
        </section>
      </main>
    );
  }

  if (session.status === "signed-out") {
    return (
      <main className="login">
        <section className="login-hero">
          <div className="sky" aria-hidden="true">
            <div className="sun" />
            <div className="hills">
              <Hills />
            </div>
            <div className="cows">
              <Cows />
            </div>
          </div>
          <div className="login-brand">
            {/* O nome da fazenda é o título da página (antes não havia h1). */}
            <h1 className="wordmark">
              <LogoMark size={52} />
              <span>
                <strong>Belo Vale II</strong>
                <small>Gestão do rebanho leiteiro</small>
              </span>
            </h1>
            <p>
              Produção, cadastro e custos da fazenda no seu bolso — do curral ao
              escritório.
            </p>
          </div>
        </section>
        <section className="login-panel">
          <LoginForm onLoggedIn={handleLoggedIn} />
        </section>
      </main>
    );
  }

  return (
    <AuthenticatedApp
      token={session.token}
      user={session.user}
      onLogout={() => void handleLogout()}
    />
  );
}

interface AuthenticatedAppProps {
  token: string;
  user: CurrentUser;
  onLogout: () => void;
}

/** Áreas do aplicativo. `painel` abre primeiro: é a visão do dia. */
type Area =
  | "painel"
  | "producao"
  | "revisao"
  | "animais"
  | "fichas"
  | "insumos"
  | "medicoes"
  | "contas"
  | "minha-conta";

const AREA_LABEL: Record<Area, string> = {
  painel: "Painel",
  producao: "Produção",
  revisao: "Revisão",
  animais: "Animais",
  fichas: "Fichas",
  insumos: "Insumos",
  medicoes: "Medições",
  contas: "Contas",
  "minha-conta": "Minha conta",
};

/** As que ficam na barra de baixo do celular; as outras vão para "Mais". */
const PRIMARY_AREAS: Area[] = ["painel", "producao", "revisao", "animais"];

const ROLE_LEVEL: Record<string, number> = {
  operator: 0,
  reviewer: 1,
  admin: 2,
};

function atLeast(user: CurrentUser, role: keyof typeof ROLE_LEVEL): boolean {
  return (ROLE_LEVEL[user.role] ?? -1) >= ROLE_LEVEL[role];
}

function initials(email: string): string {
  return email.slice(0, 2);
}

function AuthenticatedApp({
  token,
  user,
  onLogout,
}: AuthenticatedAppProps): JSX.Element {
  // A área e a ficha aberta vêm do endereço: recarregar, voltar e mandar o
  // link funcionam como se espera de qualquer página.
  const { route, navigate, replace } = useRoute();
  const [farm, setFarm] = useState<Farm | null>(null);
  const [farmError, setFarmError] = useState<string | null>(null);
  const [animal, setAnimal] = useState<AnimalDetail | null>(null);
  const [animalError, setAnimalError] = useState<string | null>(null);
  const [animalReload, setAnimalReload] = useState(0);
  const [importId, setImportId] = useState<string | null>(null);
  const [review, setReview] = useState<ImportReview | null>(null);


  // Quantas propostas esperam revisão: aparece na navegação para ninguém
  // precisar abrir a caixa para saber se há algo nela.
  const [pendingReview, setPendingReview] = useState(0);
  const refreshPending = (): void => {
    void Promise.resolve(listProposals(token, "pending"))
      .then((items) => setPendingReview(Array.isArray(items) ? items.length : 0))
      .catch(() => undefined);
  };
  useEffect(() => {
    refreshPending();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const canEdit = atLeast(user, "reviewer");
  const isAdmin = atLeast(user, "admin");

  // A fazenda vem do servidor. Ninguém digita UUID nesta aplicação.
  useEffect(() => {
    let cancelled = false;
    getCurrentFarm(token)
      .then((resolved) => {
        if (!cancelled) setFarm(resolved);
      })
      .catch((error: unknown) => {
        const body = (error as { body?: { detail?: string } })?.body;
        if (!cancelled) {
          setFarmError(
            body?.detail ??
              "Não foi possível identificar a fazenda. Fale com o administrador.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const openAnimalId = route.area === "animais" ? route.animalId : null;
  useEffect(() => {
    if (openAnimalId === null) {
      setAnimal(null);
      setAnimalError(null);
      return;
    }
    let cancelled = false;
    setAnimalError(null);
    // A ficha anterior some na hora: por um instante, o nome de uma vaca com
    // os dados de outra é pior que um instante de espera.
    setAnimal((current) => (current?.id === openAnimalId ? current : null));
    getAnimal(token, openAnimalId)
      .then((loaded) => {
        if (!cancelled) setAnimal(loaded);
      })
      .catch(() => {
        if (!cancelled) {
          setAnimalError("Não foi possível abrir esta ficha. Ela pode não existir nesta fazenda.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, openAnimalId, animalReload]);

  const openAnimal = (animalId: string): void =>
    navigate({ area: "animais", animalId });

  const refreshReview = async (id: string): Promise<void> => {
    setReview(await getImportReview(id, token));
  };

  const handleUploaded = async (result: UploadResult): Promise<void> => {
    setImportId(result.id);
    await refreshReview(result.id);
  };

  const handleDecided = async (): Promise<void> => {
    // Aprovar/rejeitar não remenda o estado local: relê a mesma fonte que o
    // GET /review usa, então substituições, versão da linha e alertas novos
    // aparecem exatamente como o backend passou a enxergar.
    if (importId !== null) {
      await refreshReview(importId);
    }
  };

  // No celular, cabem quatro áreas na barra de baixo e um "Mais" com o
  // resto; no computador, a barra mostra todas.
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => {
    if (!moreOpen) return;
    const close = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setMoreOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [moreOpen]);

  const areas: Area[] = [
    "painel",
    "producao",
    "revisao",
    "animais",
    // A foto da folha passou a ser enviada pela própria Revisão. As fichas
    // antigas continuam no banco; a área saiu do menu para não haver duas
    // telas fazendo a mesma coisa.

    "insumos",
    "medicoes",
    ...(isAdmin ? (["contas"] as Area[]) : []),
    "minha-conta",
  ];
  // Quem lança o leite abre direto no lançamento; quem acompanha a fazenda
  // abre no painel. Endereço sem área, ou de área que a pessoa não alcança
  // (Contas para quem não é administrador), cai na área inicial.
  const homeArea: Area = canEdit ? "painel" : "producao";
  const allowed = route.area !== null && areas.includes(route.area as Area);
  const area: Area = allowed ? (route.area as Area) : homeArea;
  useEffect(() => {
    if (!allowed) replace({ area: homeArea as AreaRoute, animalId: null });
  }, [allowed, homeArea, replace]);
  const setArea = (name: Area): void => navigate({ area: name as AreaRoute, animalId: null });

  useEffect(() => {
    const titulo = area === "animais" && animal && openAnimalId ? animal.name ?? animal.brinco : AREA_LABEL[area];
    document.title = titulo ? `${titulo} · Belo Vale II` : "Belo Vale II";
  }, [area, animal, openAnimalId]);

  // O voltar do celular também fecha o painel Mais. (Os toques na barra já
  // fecham por conta própria; a correção inicial do endereço não fecha.)
  useEffect(() => {
    const close = (): void => setMoreOpen(false);
    window.addEventListener("popstate", close);
    return () => window.removeEventListener("popstate", close);
  }, []);

  const moreAreas = areas.filter((name) => !PRIMARY_AREAS.includes(name));
  // No computador, Minha conta é o avatar com o e-mail, ao lado de Sair;
  // na barra seria um terceiro caminho para o mesmo lugar.
  const barAreas = areas.filter((name) => name !== "minha-conta");

  return (
    <main className="shell">
      <header className="topbar">
        <span className="wordmark">
          <LogoMark />
          <span>
            <strong>Belo Vale II</strong>
            <small>Gestão do rebanho leiteiro</small>
          </span>
        </span>
        <div className="who">
          <button
            type="button"
            className="avatar"
            aria-label="Minha conta"
            aria-current={area === "minha-conta"}
            onClick={() => setArea("minha-conta")}
          >
            {initials(user.email)}
          </button>
          <span className="email">{user.email}</span>
          {/* No celular, Sair fica em Minha conta: no topo, ao lado do
              polegar, era o botão mais fácil de tocar sem querer. */}
          <button type="button" className="link-btn logout-top" onClick={onLogout}>
            <Icons.logout /> Sair
          </button>
        </div>
      </header>

      <nav className="areanav" aria-label="Áreas">
        {barAreas.map((name) => {
          const Icon = Icons[name as IconName];
          return (
            <button
              key={name}
              type="button"
              className={PRIMARY_AREAS.includes(name) ? undefined : "nav-more-item"}
              aria-current={area === name}
              onClick={() => {
                setArea(name);
                setMoreOpen(false);
              }}
            >
              <Icon />
              {AREA_LABEL[name]}
              {name === "revisao" && pendingReview > 0 && (
                <span className="nav-badge" aria-label={`${pendingReview} pendentes`}>
                  {pendingReview}
                </span>
              )}
            </button>
          );
        })}
        {moreAreas.length > 0 && (
          <button
            type="button"
            className="nav-more"
            aria-expanded={moreOpen}
            aria-controls="mais-areas"
            aria-current={moreAreas.includes(area)}
            onClick={() => setMoreOpen((open) => !open)}
          >
            <Icons.mais />
            {moreAreas.includes(area) ? AREA_LABEL[area] : "Mais"}
          </button>
        )}
      </nav>

      {moreOpen && (
        <>
          <div className="more-backdrop" aria-hidden="true" onClick={() => setMoreOpen(false)} />
          <div className="more-sheet" id="mais-areas" role="group" aria-label="Mais áreas">
            {moreAreas.map((name) => {
              const Icon = Icons[name as IconName];
              return (
                <button
                  key={name}
                  type="button"
                  aria-current={area === name}
                  onClick={() => {
                    setArea(name);
                    setMoreOpen(false);
                  }}
                >
                  <Icon />
                  {AREA_LABEL[name]}
                </button>
              );
            })}
          </div>
        </>
      )}

      {farmError && <p role="alert">{farmError}</p>}

      <div className="area" key={area}>
        {area === "painel" && <HerdDashboard token={token} />}

        {area === "producao" && <ProductionPage token={token} canCorrect={canEdit} />}

        {area === "revisao" && (
          <ReviewInbox
            token={token}
            farmId={farm?.id}
            canDecide={canEdit}
            onChanged={refreshPending}
          />
        )}

        {area === "insumos" && (
          <SuppliesPage
            token={token}
            canEdit={canEdit}
            milkPrice={farm?.milk_price_per_liter ?? null}
            onMilkPriceSaved={(price) =>
              setFarm((current) => (current ? { ...current, milk_price_per_liter: price } : current))
            }
          />
        )}

        {area === "animais" && (
          <>
            {/* A busca fica montada por trás da ficha: voltar devolve a lista
                como estava, com o recorte e o que já tinha carregado. */}
            <div hidden={openAnimalId !== null}>
              <AnimalSearchPage token={token} canEdit={canEdit} onOpen={openAnimal} />
            </div>
            {openAnimalId !== null && (
              <>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    // Veio da lista: volta nela (o voltar do celular faz o
                    // mesmo). Chegou por link: não há o que voltar, abre a lista.
                    if ((window.history.state as { inApp?: boolean } | null)?.inApp) {
                      window.history.back();
                    } else {
                      replace({ area: "animais", animalId: null });
                    }
                  }}
                >
                  <Icons.back /> Voltar à busca
                </button>
                {animalError && <p role="alert">{animalError}</p>}
                {animal === null && !animalError && (
                  <div className="skeleton skeleton-card" aria-label="Carregando a ficha" />
                )}
                {animal !== null && (
                  <AnimalDetailPanel
                    key={animal.id}
                    token={token}
                    animal={animal}
                    canEdit={canEdit}
                    onChanged={() => setAnimalReload((count) => count + 1)}
                    onOpenAnimal={openAnimal}
                  />
                )}
              </>
            )}
          </>
        )}

        {area === "fichas" && farm !== null && (
          <>
            <h2>Fichas de medição</h2>
            <p className="muted">
              Envie a foto da ficha. O sistema lê as linhas e deixa cada uma para
              conferência antes de virar medição oficial.
            </p>
            <UploadForm token={token} farmId={farm.id} onUploaded={handleUploaded} />
            {review !== null && (
              <div>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => refreshReview(review.import_id)}
                >
                  Atualizar revisão
                </button>
                <ReviewWorkspace review={review} token={token} onDecided={handleDecided} />
              </div>
            )}
          </>
        )}

        {area === "medicoes" && farm !== null && (
          <OfficialMeasurements farmId={farm.id} token={token} />
        )}

        {area === "contas" && isAdmin && (
          <UsersPage token={token} currentUserId={user.id} />
        )}

        {area === "minha-conta" && (
          <>
            <PageHeader
              title="Minha conta"
              actions={
                <button type="button" className="secondary logout-account" onClick={onLogout}>
                  <Icons.logout /> Sair
                </button>
              }
            >
              {user.email}
            </PageHeader>
            <ChangePasswordForm token={token} />
          </>
        )}
      </div>
    </main>
  );
}
