import { useEffect, useRef, useState } from "react";

/**
 * Anima um número de 0 até o valor final.
 *
 * Desliga sob `prefers-reduced-motion` e em ambiente de teste, onde a
 * animação só atrapalharia a asserção: nesses casos devolve o valor final de
 * imediato.
 */

function motionAllowed(): boolean {
  if (import.meta.env.MODE === "test") return false;
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(() => (motionAllowed() ? 0 : target));
  const previous = useRef(motionAllowed() ? 0 : target);

  useEffect(() => {
    if (!motionAllowed()) {
      setValue(target);
      previous.current = target;
      return;
    }
    const from = previous.current;
    const start = performance.now();
    let frame = 0;

    const tick = (now: number): void => {
      const t = Math.min(1, (now - start) / duration);
      // ease-out cúbico: chega rápido e assenta devagar.
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (target - from) * eased);
      if (t < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        previous.current = target;
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return value;
}
