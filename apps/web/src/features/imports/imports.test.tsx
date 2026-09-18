import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DecisionResult, ImportReview } from "../../api/types";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { UploadForm } from "./UploadForm";

function buildReview(overrides: Partial<ImportReview["lines"][number]> = {}): ImportReview {
  return {
    import_id: "11111111-1111-1111-1111-111111111111",
    status: "extracted",
    declared_lot: "1",
    declared_measured_on: "2026-07-22",
    lines: [
      {
        id: "22222222-2222-2222-2222-222222222222",
        line_number: 1,
        version: 1,
        raw_values: { animal_number: "497" },
        normalized_values: { animal_number: "497", total: "18" },
        confidence: 0.9,
        candidate_animal_id: "33333333-3333-3333-3333-333333333333",
        crop_url: "https://storage.example/crop.jpg",
        alerts: [],
        existing_measurement: null,
        ...overrides,
      },
    ],
  };
}

describe("ReviewWorkspace", () => {
  it("shows the replacement warning before approval and requires a reason", async () => {
    const user = userEvent.setup();
    const review = buildReview({
      existing_measurement: {
        id: "44444444-4444-4444-4444-444444444444",
        measured_on: "2026-07-22",
        values: { total: "17" },
      },
    });
    const decide = vi.fn();

    render(<ReviewWorkspace review={review} decide={decide} />);

    await user.click(screen.getByRole("button", { name: "Aprovar" }));

    expect(screen.getByText(/será substituída/i)).toBeVisible();
    expect(screen.getByLabelText(/motivo da substituição/i)).toBeRequired();
    expect(screen.getByRole("button", { name: "Confirmar aprovação" })).toBeDisabled();
    expect(decide).not.toHaveBeenCalled();
  });

  it("enables confirmation once a replacement reason is provided and submits it", async () => {
    const user = userEvent.setup();
    const review = buildReview({
      existing_measurement: {
        id: "44444444-4444-4444-4444-444444444444",
        measured_on: "2026-07-22",
        values: { total: "17" },
      },
    });
    const result: DecisionResult = {
      line_id: review.lines[0].id,
      version: 2,
      measurement_id: "55555555-5555-5555-5555-555555555555",
      measurement_status: "active",
    };
    const decide = vi.fn().mockResolvedValue(result);
    const onDecided = vi.fn();

    render(<ReviewWorkspace review={review} decide={decide} onDecided={onDecided} />);

    await user.click(screen.getByRole("button", { name: "Aprovar" }));
    await user.type(screen.getByLabelText(/motivo da substituição/i), "correção confirmada");
    await user.click(screen.getByRole("button", { name: "Confirmar aprovação" }));

    await waitFor(() => expect(onDecided).toHaveBeenCalledWith(review.lines[0].id, result));
    expect(decide).toHaveBeenCalledWith(
      review.lines[0].id,
      "approve",
      null,
      "correção confirmada",
      1,
    );
  });

  it("does not require a reason to approve a line with no active measurement to replace", async () => {
    const user = userEvent.setup();
    const review = buildReview();
    const decide = vi.fn().mockResolvedValue({
      line_id: review.lines[0].id,
      version: 2,
      measurement_id: "id",
      measurement_status: "active",
    });

    render(<ReviewWorkspace review={review} decide={decide} />);

    await user.click(screen.getByRole("button", { name: "Aprovar" }));
    expect(screen.queryByText(/será substituída/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmar aprovação" }));

    await waitFor(() => expect(decide).toHaveBeenCalled());
  });

  it("renders alerts for a line", () => {
    const review = buildReview({
      alerts: [
        {
          code: "unknown_animal",
          severity: "error",
          message: "Nenhum animal cadastrado corresponde.",
          details: {},
        },
      ],
    });

    render(<ReviewWorkspace review={review} decide={vi.fn()} />);

    expect(screen.getByText("Nenhum animal cadastrado corresponde.")).toBeVisible();
  });
});

describe("UploadForm", () => {
  it("offers to reprocess when the upload is rejected as a duplicate", async () => {
    const user = userEvent.setup();
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        code: "duplicate_image",
        existing_import_id: "66666666-6666-6666-6666-666666666666",
      }),
    }) as unknown as typeof fetch;

    // A fazenda vem resolvida do servidor; o formulário não a pede mais.
    render(
      <UploadForm
        token="test-token"
        farmId="11111111-1111-1111-1111-111111111111"
      />,
    );

    const file = new File(["fake"], "sheet.jpg", { type: "image/jpeg" });
    await user.upload(screen.getByLabelText("Foto da ficha"), file);
    await user.click(screen.getByRole("button", { name: "Enviar foto" }));

    expect(await screen.findByText(/já foi enviada anteriormente/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Reprocessar mesmo assim" })).toBeEnabled();

    globalThis.fetch = originalFetch;
  });
});
