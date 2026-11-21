import { useEffect, useRef, useState, type MouseEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { mount } from "@/lib/mount";

// Aonyx, the desktop pet (an easter egg; see src-tauri/src/aonyx.rs).
// Sprite sheets: 128px frames in rows of 4, with per-frame timing from the
// asset pack, played faster (`speed`) so the pet feels lively.

type Anim = "idle" | "thinking" | "hop" | "happy" | "spin";

interface Sheet {
  src: string;
  frames: number[];
  speed: number;
}

const SHEETS: Record<Anim, Sheet> = {
  idle: {
    src: "/aonyx/aonyx_idle_sheet.png",
    frames: [350, 350, 330, 380, 370, 350, 350, 380],
    speed: 1.5,
  },
  thinking: {
    src: "/aonyx/aonyx_thinking_sheet.png",
    frames: [240, 240, 320, 340, 360, 340, 410, 330, 240, 360],
    speed: 1.8,
  },
  hop: {
    src: "/aonyx/aonyx_hopping_sheet.png",
    frames: [270, 220, 170, 120, 150, 230, 230, 140, 170, 250, 420],
    speed: 2,
  },
  happy: {
    src: "/aonyx/aonyx_happy_sheet.png",
    frames: [230, 230, 220, 280, 270, 240, 240, 310],
    speed: 1.8,
  },
  spin: {
    src: "/aonyx/aonyx_spinning_sheet.png",
    frames: [230, 230, 230, 230, 230, 230, 230, 230],
    speed: 2.2,
  },
};

const FRAME = 128;
const COLUMNS = 4;
const SIZE = 96;
// Reduced motion shows one still frame per state instead of animating.
const STILL_FRAME: Record<Anim, number> = { idle: 0, thinking: 6, hop: 0, happy: 3, spin: 6 };
const FLOURISHES: Anim[] = ["hop", "happy", "spin"];
// Pointer travel that turns a press into a drag instead of a click.
const DRAG_THRESHOLD = 4;

interface Play {
  anim: Anim;
  // Plays this many times, then returns to the base; null loops.
  loops: number | null;
}

// Follows the system setting live, not only when the page loads.
function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setReduced(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

function Aonyx() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const images = useRef<Partial<Record<Anim, HTMLImageElement>>>({});
  // The resting animation: idle, or thinking while an answer streams.
  const base = useRef<Anim>("idle");
  const [play, setPlay] = useState<Play>({ anim: "spin", loops: 1 });
  const [shown, setShown] = useState(false);
  const press = useRef<{ x: number; y: number; dragged: boolean } | null>(null);
  const reducedMotion = useReducedMotion();

  function react(anim: Anim, loops = 1) {
    setPlay({ anim, loops });
  }

  useEffect(() => {
    for (const [anim, sheet] of Object.entries(SHEETS) as [Anim, Sheet][]) {
      const image = new Image();
      image.src = sheet.src;
      images.current[anim] = image;
    }
    const appear = requestAnimationFrame(() => setShown(true));
    const unlisten = listen<string>("aonyx-state", ({ payload }) => {
      if (payload === "thinking") {
        base.current = "thinking";
        setPlay({ anim: "thinking", loops: null });
      } else if (payload === "happy") {
        base.current = "idle";
        react("happy", 2);
      } else if (payload === "hop") {
        react("hop");
      } else {
        base.current = "idle";
        setPlay({ anim: "idle", loops: null });
      }
    });
    return () => {
      cancelAnimationFrame(appear);
      void unlisten.then((stop) => stop());
    };
  }, []);

  // Now and then, while resting, a small flourish.
  useEffect(() => {
    if (reducedMotion || play.anim !== "idle") return;
    const delay = 25_000 + Math.random() * 20_000;
    const timer = setTimeout(() => {
      if (base.current === "idle") {
        react(FLOURISHES[Math.floor(Math.random() * FLOURISHES.length)] ?? "hop");
      }
    }, delay);
    return () => clearTimeout(timer);
  }, [play, reducedMotion]);

  // Draws frames on a timer; a finished one-shot returns to the base.
  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const scale = window.devicePixelRatio || 1;
    canvas.width = SIZE * scale;
    canvas.height = SIZE * scale;
    context.imageSmoothingEnabled = false;

    const sheet = SHEETS[play.anim];
    let frame = reducedMotion ? STILL_FRAME[play.anim] : 0;
    let loopsLeft = play.loops;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const draw = () => {
      const image = images.current[play.anim];
      context.clearRect(0, 0, canvas.width, canvas.height);
      if (image?.complete && image.naturalWidth > 0) {
        const sx = (frame % COLUMNS) * FRAME;
        const sy = Math.floor(frame / COLUMNS) * FRAME;
        context.drawImage(image, sx, sy, FRAME, FRAME, 0, 0, canvas.width, canvas.height);
      }
    };

    const tick = () => {
      draw();
      if (reducedMotion) {
        if (loopsLeft !== null) timer = setTimeout(() => setPlay({ anim: base.current, loops: null }), 1200);
        return;
      }
      timer = setTimeout(() => {
        frame += 1;
        if (frame >= sheet.frames.length) {
          frame = 0;
          if (loopsLeft !== null && --loopsLeft <= 0) {
            setPlay({ anim: base.current, loops: null });
            return;
          }
        }
        tick();
      }, (sheet.frames[frame] ?? 300) / sheet.speed);
    };

    const image = images.current[play.anim];
    const onLoad = () => draw();
    if (image && !image.complete) image.onload = onLoad;
    tick();
    return () => {
      clearTimeout(timer);
      // A sheet that loads after the animation changed must not draw over the new one.
      if (image && image.onload === onLoad) image.onload = null;
    };
  }, [play, reducedMotion]);

  // A press that moves drags the window; one that does not is a click.
  function onMouseDown(event: MouseEvent) {
    if (event.button !== 0) return;
    press.current = { x: event.screenX, y: event.screenY, dragged: false };
  }

  function onMouseMove(event: MouseEvent) {
    const p = press.current;
    if (!p || p.dragged) return;
    if (Math.hypot(event.screenX - p.x, event.screenY - p.y) > DRAG_THRESHOLD) {
      p.dragged = true;
      void getCurrentWindow().startDragging();
    }
  }

  function onMouseUp(event: MouseEvent) {
    const p = press.current;
    press.current = null;
    if (event.button !== 0 || !p || p.dragged) return;
    react("hop");
    void invoke("aonyx_clicked");
  }

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label="Aonyx, the Onyx otter. Click to open the launcher."
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={() => {
        if (press.current && !press.current.dragged) press.current = null;
      }}
      onContextMenu={(event) => {
        event.preventDefault();
        void invoke("aonyx_menu");
      }}
      style={{ width: SIZE, height: SIZE }}
      className={`block cursor-pointer transition-[opacity,transform] duration-300 ease-out ${
        shown ? "scale-100 opacity-100" : "scale-75 opacity-0"
      }`}
    />
  );
}

mount(<Aonyx />, "aonyx");
