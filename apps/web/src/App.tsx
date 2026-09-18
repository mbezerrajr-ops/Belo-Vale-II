import { useEffect, useState } from "react";

import {
  getAnimal,
  getCurrentFarm,
  getCurrentUser,
  getImportReview,
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
import { AnimalDetailPanel } from "./features/animals/AnimalDetailPanel";
import { HerdDashboard } from "./features/dashboard/HerdDashboard";
import { SuppliesPage } from "./features/dashboard/SuppliesPage";
import { AnimalSearchPage } from "./features/animals/AnimalSearchPage";
import { ChangePasswordForm } from "./features/users/ChangePasswordForm";
import { UsersPage } from "./features/users/UsersPage";
import { LoginForm } from "./auth/LoginForm";
import { clearStoredToken, loadStoredToken, storeToken } from "./auth/session";
import { OfficialMeasurements } from "./features/dashboard/OfficialMeasurements";
import { ReviewWorkspace } from "./features/imports/ReviewWorkspace";
import { UploadForm } from "./features/imports/UploadForm";

type SessionState =
  | { status: "checking" }
  | { status: "signed-out" }
  | { status: "signed-in"; token: string; user: CurrentUser };

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
      // Bem antes dos 15 minutos do token, com folga para uma falha de rede.
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

  const handleLogout = (): void => {
    // Revoga no servidor: apagar o token só do navegador deixaria a sessão
    // viva para quem tivesse o cookie.
    void endSession().catch(() => {
      // Mesmo se a chamada falhar, o acesso local é encerrado.
    });
    clearStoredToken();
    setSession({ status: "signed-out" });
  };

  if (session.status === "checking") {
    return <p>Carregando…</p>;
  }

  if (session.status === "signed-out") {
    return (
      <main>
        <h1>Belo Vale II</h1>
        <LoginForm onLoggedIn={handleLoggedIn} />
      </main>
    );
  }

  return (
    <AuthenticatedApp
      token={session.token}
      user={session.user}
      onLogout={handleLogout}
    />
  );
}

interface AuthenticatedAppProps {
  token: string;
  user: CurrentUser;
  onLogout: () => void;
}

/** Áreas do aplicativo. `animais` é a primeira porque é o uso diário. */
type Area =
  | "painel"
  | "animais"
  | "fichas"
  | "insumos"
  | "medicoes"
  | "contas"
  | "minha-conta";

const ROLE_LEVEL: Record<string, number> = {
  operator: 0,
  reviewer: 1,
  admin: 2,
};

function atLeast(user: CurrentUser, role: keyof typeof ROLE_LEVEL): boolean {
  return (ROLE_LEVEL[user.role] ?? -1) >= ROLE_LEVEL[role];
}

function AuthenticatedApp({
  token,
  user,
  onLogout,
}: AuthenticatedAppProps): JSX.Element {
  const [area, setArea] = useState<Area>("painel");
  const [farm, setFarm] = useState<Farm | null>(null);
  const [farmError, setFarmError] = useState<string | null>(null);
  const [openAnimalId, setOpenAnimalId] = useState<string | null>(null);
  const [animal, setAnimal] = useState<AnimalDetail | null>(null);
  const [importId, setImportId] = useState<string | null>(null);
  const [review, setReview] = useState<ImportReview | null>(null);

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

  const loadAnimal = async (animalId: string): Promise<void> => {
    setOpenAnimalId(animalId);
    setAnimal(await getAnimal(token, animalId));
  };

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

  return (
    <main>
      <header>
        <h1>Belo Vale II</h1>
        <p className="who">
          {user.email}
          <button type="button" onClick={onLogout}>
            Sair
          </button>
        </p>
      </header>

      <nav aria-label="Áreas">
        <button
          type="button"
          aria-current={area === "painel"}
          onClick={() => setArea("painel")}
        >
          Painel
        </button>
        <button
          type="button"
          aria-current={area === "animais"}
          onClick={() => setArea("animais")}
        >
          Animais
        </button>
        <button
          type="button"
          aria-current={area === "fichas"}
          onClick={() => setArea("fichas")}
        >
          Fichas
        </button>
        <button
          type="button"
          aria-current={area === "insumos"}
          onClick={() => setArea("insumos")}
        >
          Insumos
        </button>
        <button
          type="button"
          aria-current={area === "medicoes"}
          onClick={() => setArea("medicoes")}
        >
          Medições
        </button>
        {isAdmin && (
          <button
            type="button"
            aria-current={area === "contas"}
            onClick={() => setArea("contas")}
          >
            Contas
          </button>
        )}
        <button
          type="button"
          aria-current={area === "minha-conta"}
          onClick={() => setArea("minha-conta")}
        >
          Minha conta
        </button>
      </nav>

      {farmError && <p role="alert">{farmError}</p>}

      {area === "painel" && <HerdDashboard token={token} />}

      {area === "insumos" && (
        <SuppliesPage
          token={token}
          canEdit={canEdit}
          milkPrice={farm?.milk_price_per_liter ?? null}
        />
      )}

      {area === "animais" &&
        (openAnimalId !== null && animal !== null ? (
          <>
            <button type="button" onClick={() => setOpenAnimalId(null)}>
              Voltar à busca
            </button>
            <AnimalDetailPanel
              token={token}
              animal={animal}
              canEdit={canEdit}
              onChanged={() => void loadAnimal(animal.id)}
            />
          </>
        ) : (
          <AnimalSearchPage
            token={token}
            canEdit={canEdit}
            onOpen={(animalId) => void loadAnimal(animalId)}
          />
        ))}

      {area === "fichas" && farm !== null && (
        <>
          <UploadForm token={token} farmId={farm.id} onUploaded={handleUploaded} />
          {review !== null && (
            <div>
              <button type="button" onClick={() => refreshReview(review.import_id)}>
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

      {area === "minha-conta" && <ChangePasswordForm token={token} />}
    </main>
  );
}
