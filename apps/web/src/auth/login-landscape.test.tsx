/**
 * A paisagem do login: as vacas pastando atrás de camadas de papel.
 *
 * É decoração. Não recebe foco nem clique, some para leitores de tela, e quem
 * pediu menos movimento (ou está economizando dados no 3G do curral) vê só a
 * imagem parada — o vídeo nem é baixado.
 */

import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginLandscape } from "./LoginLandscape";

function preferenciaDeMovimento(reduzir: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduzir && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "connection");
});

describe("Paisagem do login", () => {
  it("toca o vídeo mudo, em loop, sem controles e fora dos leitores de tela", () => {
    preferenciaDeMovimento(false);

    const { container } = render(<LoginLandscape />);

    const paisagem = container.firstElementChild as HTMLElement;
    expect(paisagem).toHaveAttribute("aria-hidden", "true");
    const video = container.querySelector("video") as HTMLVideoElement;
    expect(video).not.toBeNull();
    expect(video.muted).toBe(true);
    expect(video.autoplay).toBe(true);
    expect(video.loop).toBe(true);
    expect(video).toHaveAttribute("playsinline");
    expect(video).not.toHaveAttribute("controls");
    // O pôster aparece enquanto o vídeo carrega.
    expect(video.getAttribute("poster")).toMatch(/login-cattle-poster\.webp$/);
    expect(container.querySelector("source")?.getAttribute("src")).toMatch(
      /login-cattle-animation\.mp4$/,
    );
  });

  it("com movimento reduzido, só a imagem parada: o vídeo nem é carregado", () => {
    preferenciaDeMovimento(true);

    const { container } = render(<LoginLandscape />);

    expect(container.querySelector("video")).toBeNull();
    const imagem = container.querySelector("img") as HTMLImageElement;
    expect(imagem.getAttribute("src")).toMatch(/login-cattle-poster\.webp$/);
    expect(imagem).toHaveAttribute("alt", "");
  });

  it("economizando dados, também só a imagem parada", () => {
    preferenciaDeMovimento(false);
    Object.defineProperty(navigator, "connection", {
      configurable: true,
      value: { saveData: true },
    });

    const { container } = render(<LoginLandscape />);

    expect(container.querySelector("video")).toBeNull();
    expect(container.querySelector("img")).not.toBeNull();
  });
});
