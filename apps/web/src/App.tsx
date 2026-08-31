import { useEffect, useState } from "react";

import { getCurrentUser, getImportReview } from "./api/client";
import type { CurrentUser, ImportReview, UploadResult } from "./api/types";
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
    const storedToken = loadStoredToken();
    if (storedToken === null) {
      setSession({ status: "signed-out" });
      return;
    }
    getCurrentUser(storedToken)
      .then((user) => setSession({ status: "signed-in", token: storedToken, user }))
      .catch(() => {
        clearStoredToken();
        setSession({ status: "signed-out" });
      });
  }, []);

  const handleLoggedIn = async (loginResult: { access_token: string }): Promise<void> => {
    const token = loginResult.access_token;
    const user = await getCurrentUser(token);
    storeToken(token);
    setSession({ status: "signed-in", token, user });
  };

  const handleLogout = (): void => {
    clearStoredToken();
    setSession({ status: "signed-out" });
  };

  if (session.status === "checking") {
    return <p>Carregando…</p>;
  }

  if (session.status === "signed-out") {
    return (
      <main>
        <h1>Belo Vale — Conferência de fichas</h1>
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

function AuthenticatedApp({
  token,
  user,
  onLogout,
}: AuthenticatedAppProps): JSX.Element {
  const [farmId, setFarmId] = useState("");
  const [importId, setImportId] = useState<string | null>(null);
  const [review, setReview] = useState<ImportReview | null>(null);

  const refreshReview = async (id: string): Promise<void> => {
    const nextReview = await getImportReview(id, token);
    setReview(nextReview);
  };

  const handleUploaded = async (result: UploadResult): Promise<void> => {
    setImportId(result.id);
    await refreshReview(result.id);
  };

  const handleDecided = async (): Promise<void> => {
    // Approving/rejecting doesn't optimistically patch local state — this
    // just re-fetches the same source of truth GET /review already reads,
    // so an approval's supersession side effects, updated line version, and
    // any new alerts show up exactly as the backend now sees them.
    if (importId !== null) {
      await refreshReview(importId);
    }
  };

  return (
    <main>
      <header>
        <h1>Belo Vale — Conferência de fichas</h1>
        <p>
          {user.email} ({user.role})
          <button type="button" onClick={onLogout}>
            Sair
          </button>
        </p>
      </header>

      <label>
        Fazenda
        <input value={farmId} onChange={(event) => setFarmId(event.target.value)} />
      </label>

      <UploadForm token={token} onUploaded={handleUploaded} />
      {review === null ? null : (
        <div>
          <button type="button" onClick={() => refreshReview(review.import_id)}>
            Atualizar revisão
          </button>
          <ReviewWorkspace review={review} token={token} onDecided={handleDecided} />
        </div>
      )}
      {farmId === "" ? null : <OfficialMeasurements farmId={farmId} token={token} />}
    </main>
  );
}
