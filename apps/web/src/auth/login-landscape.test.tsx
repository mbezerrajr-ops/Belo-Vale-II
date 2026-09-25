/**
 * A paisagem do login: as vacas pastando na moldura de papel.
 *
 * É decoração. Não recebe foco nem clique, some para leitores de tela, e quem
 * pediu menos movimento (ou está economizando dados no 3G do curral) vê só a
 * imagem parada — o vídeo nem é baixado. No computador vem a janela de papel
 * inteira; no celular, a paisagem do pé da tela. Nunca as duas.
 */

import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginBranch, LoginLandscape } from "./LoginLandscape";

function ambiente({ reduzir = false, largo = false } = {}): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches:
        (reduzir && query.includes("prefers-reduced-motion")) ||
        (largo && query.includes("min-width: 880px")),
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
    ambiente();

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
    expect(container.querySelectorAll("video")).toHaveLength(1);
  });

  it("no celular, a paisagem do pé da tela", () => {
    ambiente();

    const { container } = render(<LoginLandscape />);

    const video = container.querySelector("video") as HTMLVideoElement;
    expect(video.getAttribute("poster")).toMatch(/login-cattle-mobile-poster\.webp$/);
    expect(container.querySelector("source")?.getAttribute("src")).toMatch(
      /login-cattle-mobile\.mp4$/,
    );
  });

  it("no computador, a janela de papel inteira", () => {
    ambiente({ largo: true });

    const { container } = render(<LoginLandscape />);

    const video = container.querySelector("video") as HTMLVideoElement;
    expect(video.getAttribute("poster")).toMatch(/login-cattle-poster\.webp$/);
    expect(container.querySelector("source")?.getAttribute("src")).toMatch(
      /login-cattle-animation\.mp4$/,
    );
  });

  it("com movimento reduzido, só a imagem parada: o vídeo nem é carregado", () => {
    ambiente({ reduzir: true });

    const { container } = render(<LoginLandscape />);

    expect(container.querySelector("video")).toBeNull();
    const imagem = container.querySelector("img") as HTMLImageElement;
    expect(imagem.getAttribute("src")).toMatch(/login-cattle-mobile-poster\.webp$/);
    expect(imagem).toHaveAttribute("alt", "");
  });

  it("economizando dados, também só a imagem parada", () => {
    ambiente();
    Object.defineProperty(navigator, "connection", {
      configurable: true,
      value: { saveData: true },
    });

    const { container } = render(<LoginLandscape />);

    expect(container.querySelector("video")).toBeNull();
    expect(container.querySelector("img")).not.toBeNull();
  });

  it("o galho do canto também é decoração", () => {
    const { container } = render(<LoginBranch />);

    const galho = container.querySelector("img") as HTMLImageElement;
    expect(galho).toHaveAttribute("aria-hidden", "true");
    expect(galho).toHaveAttribute("alt", "");
    expect(galho.getAttribute("src")).toMatch(/login-branch\.webp$/);
  });
});
