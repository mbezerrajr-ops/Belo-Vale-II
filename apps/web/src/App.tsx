import { useState } from "react";

import { getImportReview } from "./api/client";
import type { ImportReview, UploadResult } from "./api/types";
import { ReviewWorkspace } from "./features/imports/ReviewWorkspace";
import { UploadForm } from "./features/imports/UploadForm";

export function App(): JSX.Element {
  const [token, setToken] = useState("");
  const [review, setReview] = useState<ImportReview | null>(null);

  const handleUploaded = async (result: UploadResult): Promise<void> => {
    const nextReview = await getImportReview(result.id, token);
    setReview(nextReview);
  };

  return (
    <main>
      <h1>Belo Vale — Conferência de fichas</h1>
      <label>
        Token de acesso
        <input value={token} onChange={(event) => setToken(event.target.value)} />
      </label>
      <UploadForm token={token} onUploaded={handleUploaded} />
      {review === null ? null : <ReviewWorkspace review={review} token={token} />}
    </main>
  );
}
