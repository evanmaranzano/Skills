// Qwen38Deploy — atelier bespoke composition（OpenMontage hybrid pipeline, compose 阶段）
// ─────────────────────────────────────────────────────────────────────────────
// 自包含 Remotion 工程：10 场景 / 64s / 1920×1080@30。手法逐条对应
// scene_plan.metadata.shotcraft.cards 点名的 10 张配方卡（见 art-direction.md）。
// atelier 教条：零 stock-registry import，只依赖 remotion/react 引擎知识。
// 确定性渲染：无 Date.now/Math.random；伪随机走固定种子哈希 h()。
// 音频是时间线级资产（sound-design §1）：本文件集中管理 BGM 包络/旁白/SFX 三张表。
import React, { useEffect, useState } from 'react';
import {
  AbsoluteFill,
  Audio,
  Composition,
  OffthreadVideo,
  Sequence,
  Easing,
  interpolate,
  interpolateColors,
  registerRoot,
  staticFile,
  useCurrentFrame,
  delayRender,
  continueRender,
} from 'remotion';

// ─── 全局常量 ────────────────────────────────────────────────────────────────
const FPS = 30;
const W = 1920;
const H = 1080;
const DURATION = 1920; // 64s

const FONT_SANS = '"Noto Sans SC", sans-serif';
const FONT_SERIF = '"Noto Serif SC", serif';
const FONT_MONO = '"DejaVu Sans Mono", Menlo, Consolas, monospace';
// 混排场景（拉丁数字 + CJK）：等宽优先、CJK 回退 Noto Sans SC（防豆腐块）
const FONT_MONO_CJK = '"DejaVu Sans Mono", "Noto Sans SC", monospace';

// 色板（art-direction.md §色板）
const BG = '#0A0E14';
const PANEL = '#11161F';
const LINE = '#232B38';
const INK = '#E8ECF3';
const MUTED = '#8B93A5';
const ACCENT = '#5B8DEF';
const ACCENT_HI = '#8FB2F7';
const AMBER = '#C97B2E';
const AMBER_DARK = '#A85B12';
const WARN = '#E5484D';
const GOLD = '#F2C14E';
const PAPER = '#FAF7F2';
const PAPER_INK = '#1A1A18';
const PAPER_MUTED = '#6B6560';

// 固定种子伪随机（确定性渲染硬规则）
const h = (n: number): number => {
  const s = Math.sin(n * 127.3) * 43758.5453;
  return s - Math.floor(s);
};

// 归一化进度 [a,b] → [0,1]，两端 clamp
const seg = (f: number, a: number, b: number): number =>
  interpolate(f, [a, b], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

// ─── 字体：@font-face 装载 public/fonts（渲染机无 CJK 系统字体、无出网）─────────
const FONT_CSS = `
@font-face {
  font-family: 'Noto Sans SC';
  src: url('${staticFile('fonts/NotoSansSC-VF.ttf')}') format('truetype');
  font-weight: 100 900;
  font-display: block;
}
@font-face {
  font-family: 'Noto Serif SC';
  src: url('${staticFile('fonts/NotoSerifSC-VF.ttf')}') format('truetype');
  font-weight: 100 900;
  font-display: block;
}
`;

// 字体门：首帧前把用到的字重全部加载完（无网络，全部本地）
const FontGate: React.FC = () => {
  const [handle] = useState(() => delayRender('font-load'));
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const fontsApi = (document as unknown as { fonts: FontFaceSet }).fonts;
        await Promise.all([
          fontsApi.load('500 100px "Noto Sans SC"'),
          fontsApi.load('600 100px "Noto Sans SC"'),
          fontsApi.load('800 100px "Noto Sans SC"'),
          fontsApi.load('600 100px "Noto Serif SC"'),
          fontsApi.load('300 100px "Noto Serif SC"'),
        ]);
        await fontsApi.ready;
      } catch (e) {
        // 字体加载失败不阻塞渲染（fallback 到系统字体，抽帧自审会发现）
      } finally {
        if (alive) continueRender(handle);
      }
    })();
    return () => {
      alive = false;
    };
  }, [handle]);
  return null;
};

// ─── 音频时间线（声音是时间线级资产，集中管理）────────────────────────────────
// BGM 包络：0.34 铺底 + 旁白段 -6dB ducking（6f attack / 24f release 斜坡）
// + s10 让位 H3 环境音床（0.15）+ 首尾淡入淡出。预计算 1f 分辨率，确定性。
const DUCK_WINDOWS: [number, number, number][] = [
  [6, 115, 0.17],      // s1 旁白 0.4–3.0s
  [183, 413, 0.17],    // s2 旁白 6.3–13.0s
  [423, 641, 0.17],    // s3 旁白 14.3–20.6s
  [720, 1039, 0.17],   // s5 旁白 24.2–33.8s
  [1083, 1571, 0.17],  // s7+s8 旁白 36.3–51.6s（两窗相连取并集）
  [1563, 1762, 0.17],  // s9 旁白 52.3–58.5s（与上窗尾部重叠，min 自然合并）
  [1743, 1919, 0.17],  // s10 旁白 58.3–63.0s
];
const BGM_ENVELOPE: number[] = (() => {
  const arr = new Array<number>(DURATION + 1);
  for (let f = 0; f <= DURATION; f++) {
    let v = interpolate(f, [0, 45], [0, 0.34], { extrapolateRight: 'clamp' });
    for (const [a, b, t] of DUCK_WINDOWS) {
      if (f >= a && f <= b) {
        const gIn = seg(f, a, a + 6);
        const gOut = 1 - seg(f, b - 24, b);
        const g = Math.min(gIn, gOut);
        v = Math.min(v, 0.34 - (0.34 - t) * g);
      }
    }
    v *= interpolate(f, [1860, DURATION], [1, 0], { extrapolateLeft: 'clamp' });
    arr[f] = v;
  }
  return arr;
})();

// 旁白钉点（edit_decisions audio.narration.segments，8 段含 s10）。
// s10 冲突裁决（主控核实）：按 script 定稿有旁白（"三个教训…"@58.3s，4.7s）；
// edit_decisions.metadata.h3_mixing 的"无旁白"注释是 scene_plan 早期陈旧设想，
// 与 script/SRT/narration.segments 三方不一致，以脚本定稿为准 → s10 H3 压 0.15
// （与 s2/s7 一致），BGM 按旁白段 ducking 0.17。裁决记录见 render_report 草稿。
const NARRATION: { from: number; dur: number; src: string }[] = [
  { from: 12, dur: 80, src: 'assets/audio/narration/s1.wav' },
  { from: 189, dur: 201, src: 'assets/audio/narration/s2.wav' },
  { from: 429, dur: 189, src: 'assets/audio/narration/s3.wav' },
  { from: 726, dur: 290, src: 'assets/audio/narration/s5.wav' },
  { from: 1089, dur: 246, src: 'assets/audio/narration/s7.wav' },
  { from: 1329, dur: 218, src: 'assets/audio/narration/s8.wav' },
  { from: 1569, dur: 188, src: 'assets/audio/narration/s9.wav' },
  { from: 1749, dur: 142, src: 'assets/audio/narration/s10.wav' },
];

// SFX 钉帧表（S2 声明式集中管理，逐条注释对应画面动作）
const SFX: { from: number; dur: number; src: string; vol: number; note: string }[] = [
  { from: 665, dur: 34, src: 'assets/audio/sfx/paper-slide.mp3', vol: 0.8, note: 's4 纸卡压印落定' },
  { from: 1025, dur: 34, src: 'assets/audio/sfx/paper-slide.mp3', vol: 0.8, note: 's6 纸卡压印落定' },
  { from: 618, dur: 26, src: 'assets/audio/sfx/clock-tick-single.mp3', vol: 0.7, note: 's3 数值落定单 tick' },
  { from: 1686, dur: 151, src: 'assets/audio/sfx/countdown-bleeps.mp3', vol: 0.9, note: 's9 数字锁定段 bed' },
  { from: 780, dur: 7, src: 'assets/audio/sfx/ui-click-tone.mp3', vol: 0.5, note: 's5 高亮旗落位（终端叙事，系统音例外条款）' },
  { from: 1386, dur: 63, src: 'assets/audio/sfx/ui-notify-tech.mp3', vol: 0.8, note: 's8 红框标注弹出（系统叙事例外条款）' },
];

// ─── 双人对谈字幕（晓晓=主持/X，云希=工程师/Y）+ 说话人时间轴 ──────────────
// 每句 from/to 由 edge-tts 实测时长换算（30fps），与 NARRATION 音频对齐。
// spk: 'X'=晓晓(粉) / 'Y'=云希(蓝)。s4/s6 为纯视觉纸卡，无旁白无字幕。
export type Speaker = 'X' | 'Y';
export const SPK_COLOR: Record<Speaker, string> = {
  X: '#F472B6', // 晓晓 · 暖粉
  Y: '#5B8DEF', // 云希 · 蓝
};
export const SPK_NAME: Record<Speaker, string> = { X: '晓晓', Y: '云希' };

export interface Cue { from: number; to: number; spk: Speaker; lines: string[] }
export const SUBTITLES: Cue[] = [
  { from: 12, to: 92, spk: 'X', lines: ['Qwen3.8 部署踩坑记。'] },
  { from: 189, to: 300, spk: 'X', lines: ['双卡 A800，张量并行，', '二十六万上下文。'] },
  { from: 305, to: 388, spk: 'Y', lines: ['上线那天，吞吐只有四十六。'] },
  { from: 429, to: 466, spk: 'X', lines: ['第一坑。'] },
  { from: 472, to: 615, spk: 'Y', lines: ['启动脚本丢了个续行符，', 'MTP 直接静默失效。'] },
  { from: 726, to: 782, spk: 'X', lines: ['第二坑，更隐蔽。'] },
  { from: 788, to: 1011, spk: 'Y', lines: ['前缀缓存命中率百分之六十六，', '但 vLLM 不返回 cached_tokens，', '你根本不知道缓存在干活。'] },
  { from: 1089, to: 1126, spk: 'X', lines: ['调完呢？'] },
  { from: 1132, to: 1318, spk: 'Y', lines: ['显存利用率从 0.85 拉到 0.90，', 'KV 池三十三万 token，', '并发提了一成。'] },
  { from: 1329, to: 1364, spk: 'X', lines: ['第三坑。'] },
  { from: 1369, to: 1547, spk: 'Y', lines: ['重启时 pgrep 抓到 fork 子进程，', '一误杀引擎就半死，', 'health 还照样返回 200。'] },
  { from: 1569, to: 1606, spk: 'X', lines: ['修完呢？'] },
  { from: 1612, to: 1748, spk: 'Y', lines: ['吞吐七十五 token 每秒，', '提速六成，贴到双卡带宽墙了。'] },
  { from: 1749, to: 1784, spk: 'X', lines: ['三个教训——'] },
  { from: 1787, to: 1888, spk: 'Y', lines: ['参数核对、指标验证、', '重启认主进程。'] },
];

// ─── 共用件 ──────────────────────────────────────────────────────────────────

// 场景壳：fade（9f）/ cut（0f）在时间线层统一兑现（转场只允许 {fade,cut,none}）
const SceneShell: React.FC<{
  from: number;
  durationInFrames: number;
  fadeIn: number;
  fadeOut: number;
  children: React.ReactNode;
}> = ({ from, durationInFrames, fadeIn, fadeOut, children }) => (
  <Sequence from={from} durationInFrames={durationInFrames} name={`scene@${from}`}>
    <SceneFade fadeIn={fadeIn} fadeOut={fadeOut} durationInFrames={durationInFrames}>
      {children}
    </SceneFade>
  </Sequence>
);

const SceneFade: React.FC<{
  fadeIn: number;
  fadeOut: number;
  durationInFrames: number;
  children: React.ReactNode;
}> = ({ fadeIn, fadeOut, durationInFrames, children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [0, Math.max(fadeIn, 0.001), durationInFrames - Math.max(fadeOut, 0.001), durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

// H3 素材 full-bleed cover（1344×768 → 1920×1080，竖裁 ~0.8%）+ Ken Burns 缓推
// （768p 对策：full-bleed 带运动，禁静止放大）
const H3Clip: React.FC<{
  src: string;
  zoomFrom: number;
  zoomTo: number;
  dim: number;
  volume: number | ((f: number) => number);
  durationInFrames: number;
}> = ({ src, zoomFrom, zoomTo, dim, volume, durationInFrames }) => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, durationInFrames], [zoomFrom, zoomTo], {
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{ backgroundColor: '#05070B' }}>
      <AbsoluteFill
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: 'center center',
          overflow: 'hidden',
        }}
      >
        <OffthreadVideo
          src={staticFile(src)}
          volume={volume}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </AbsoluteFill>
      <AbsoluteFill style={{ backgroundColor: `rgba(6,10,16,${dim})` }} />
    </AbsoluteFill>
  );
};

// 字幕条：bottom-center 贴底，小字号轻遮挡，按说话人着色（双人对谈版）
const Subtitles: React.FC = () => {
  const frame = useCurrentFrame();
  const cue = SUBTITLES.find((s) => frame >= s.from && frame < s.to);
  if (!cue) return null;
  const opacity = interpolate(frame, [cue.from, cue.from + 4, cue.to - 4, cue.to], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const color = SPK_COLOR[cue.spk];
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        paddingBottom: 48,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          opacity,
          maxWidth: 1500,
          textAlign: 'center',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 10,
            backgroundColor: `rgba(0,0,0,0.55)`,
            borderRadius: 8,
            padding: '5px 18px 7px',
            marginBottom: 8,
            borderLeft: `4px solid ${color}`,
            fontFamily: FONT_SANS,
            fontWeight: 700,
            fontSize: 30,
            color,
            letterSpacing: 2,
          }}
        >
          {SPK_NAME[cue.spk]}
        </div>
        {cue.lines.map((l, i) => (
          <div
            key={i}
            style={{
              fontFamily: FONT_SANS,
              fontWeight: 600,
              fontSize: 42,
              lineHeight: 1.3,
              color: '#FFFFFF',
              WebkitTextStroke: '2px rgba(0,0,0,0.9)',
              paintOrder: 'stroke fill',
              textShadow: '0 2px 10px rgba(0,0,0,0.7)',
            }}
          >
            {l}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// 双人说话人角标：左下角两个圆形头像，当前说话人发光放大，另一个变暗。
// 播客感视觉锚点；与字幕顶部色条/名字 chip 三重指示谁在说话。
const SpeakerBadges: React.FC = () => {
  const frame = useCurrentFrame();
  const cue = SUBTITLES.find((s) => frame >= s.from && frame < s.to);
  const active = cue?.spk ?? null;

  const Avatar: React.FC<{ spk: Speaker; label: string; glyph: string }> = ({ spk, label, glyph }) => {
    const isActive = active === spk;
    const color = SPK_COLOR[spk];
    // 激活弹入 / 非激活收缩淡出
    const scale = isActive
      ? interpolate(frame, [cue!.from, cue!.from + 6], [0.85, 1], {
          extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
          easing: Easing.out(Easing.back(1.5)),
        })
      : 1;
    const opacity = active === null ? 0.55 : isActive ? 1 : 0.35;
    const glow = isActive ? 0.55 + 0.15 * Math.sin(frame * 0.18) : 0;
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          opacity,
          transform: `scale(${scale})`,
          transition: 'none',
        }}
      >
        <div
          style={{
            width: 84,
            height: 84,
            borderRadius: '50%',
            background: `radial-gradient(circle at 35% 30%, ${color}33, ${color}14)`,
            border: `3px solid ${color}`,
            boxShadow: isActive
              ? `0 0 ${24 + glow * 30}px ${color}${Math.round(glow * 180).toString(16).padStart(2, '0')}, inset 0 0 18px ${color}44`
              : 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: FONT_SANS,
            fontWeight: 800,
            fontSize: 40,
            color,
          }}
        >
          {glyph}
        </div>
        <div
          style={{
            fontFamily: FONT_SANS,
            fontWeight: 700,
            fontSize: 30,
            color: isActive ? color : MUTED,
            letterSpacing: 1,
          }}
        >
          {label}
        </div>
      </div>
    );
  };

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'flex-start',
        paddingLeft: 80,
        paddingBottom: 110,
        pointerEvents: 'none',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <Avatar spk="X" label="晓晓" glyph="晓" />
        <Avatar spk="Y" label="云希" glyph="希" />
      </div>
    </AbsoluteFill>
  );
};

// ─── s1 · brand-ink-open（0–180f）────────────────────────────────────────────
// 墨线十字准星描画 → 字标逐字压印（letterpress 三件套）→ 打字机副标 →
// 字标落定 hold ≥1s → 上浮消散。纸墨质地（PAPER 底 + serif）。
const WORDMARK = 'Qwen3.8-27B 部署踩坑记';
const KICKER = 'DEPLOY POSTMORTEM · 2026-08';

const Scene1BrandInk: React.FC = () => {
  const frame = useCurrentFrame();
  // 准星：竖 0→9f、横 8→18f，24→34f 淡出
  const vDraw = interpolate(frame, [0, 9], [100, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });
  const hDraw = interpolate(frame, [8, 18], [100, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.linear,
  });
  const crossFade = interpolate(frame, [24, 34], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // 副标打字机 0.7f/字符（装饰小字定式）
  const kickStart = 30;
  const kickChars = Math.floor(Math.max(0, frame - kickStart) / 0.7);
  const kickDone = kickStart + KICKER.length * 0.7;
  const cursorOn = (() => {
    if (frame < kickStart) return false;
    if (frame < kickDone) return true;
    if (frame > 120) return false;
    return Math.floor((frame - kickDone) / 2) % 2 === 0;
  })();
  // 退场 150→167f：上浮 40px + 缩 12% + 淡出（退场快于入场）
  const out = seg(frame, 150, 167);
  const groupOpacity = 1 - out;
  const groupY = -out * 40;
  const groupScale = 1 - out * 0.12;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: PAPER,
        backgroundImage:
          'radial-gradient(1100px 750px at 50% 42%, rgba(255,252,244,0.9), transparent 65%)',
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <div
        style={{
          textAlign: 'center',
          opacity: groupOpacity,
          transform: `translateY(${groupY}px) scale(${groupScale})`,
        }}
      >
        <svg
          width={64}
          height={64}
          viewBox="0 0 64 64"
          style={{ display: 'block', margin: '0 auto 34px', opacity: crossFade }}
        >
          <line
            x1={32} y1={2} x2={32} y2={62}
            stroke={AMBER_DARK} strokeWidth={5} strokeLinecap="round"
            pathLength={100} strokeDasharray={100} strokeDashoffset={vDraw}
          />
          <line
            x1={2} y1={32} x2={62} y2={32}
            stroke={AMBER_DARK} strokeWidth={5} strokeLinecap="round"
            pathLength={100} strokeDasharray={100} strokeDashoffset={hDraw}
          />
        </svg>
        <div
          style={{
            fontFamily: FONT_SERIF,
            fontSize: 96,
            fontWeight: 600,
            color: PAPER_INK,
            letterSpacing: '-0.01em',
            lineHeight: 1,
            display: 'inline-flex',
            alignItems: 'flex-end',
          }}
        >
          {WORDMARK.split('').map((ch, i) => {
            const delay = 12 + i * 3;
            const t = interpolate(frame, [delay, delay + 12], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
              easing: Easing.bezier(0.2, 0.7, 0.25, 1),
            });
            const glint = interpolate(frame, [delay + 8, delay + 12, delay + 16], [0, 1, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            return (
              <span
                key={i}
                style={{
                  position: 'relative',
                  display: 'inline-block',
                  opacity: t,
                  transform: `scale(${1.6 - 0.6 * t})`,
                  transformOrigin: 'center bottom',
                  filter: `blur(${(1 - t) * 6}px)`,
                }}
              >
                {ch === ' ' ? ' ' : ch}
                <span
                  style={{
                    position: 'absolute',
                    left: '50%',
                    bottom: -6,
                    transform: 'translateX(-50%)',
                    width: `${glint * 100}%`,
                    height: 3,
                    background: AMBER_DARK,
                    opacity: glint,
                    borderRadius: 2,
                  }}
                />
              </span>
            );
          })}
        </div>
        <div
          style={{
            fontFamily: FONT_MONO,
            fontSize: 26,
            letterSpacing: '0.14em',
            color: PAPER_MUTED,
            marginTop: 34,
            textTransform: 'uppercase',
            height: 32,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
          }}
        >
          <span style={{ whiteSpace: 'pre' }}>{KICKER.slice(0, kickChars)}</span>
          <span
            style={{
              display: 'inline-block',
              width: 14,
              height: 24,
              marginLeft: 4,
              background: AMBER_DARK,
              opacity: cursorOn ? 0.85 : 0,
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── s2 · spotlight-hero-card（180–420f）──────────────────────────────────────
// H3 数据中心 full-bleed 缓推（cover）+ 压暗 0.55 + 矢量标题/stat 角标。
// 单主角立传：主角 = H3 素材本身；矢量层只做"标签"，不抢焦点。
const Scene2H3Datacenter: React.FC = () => {
  const frame = useCurrentFrame();
  const titleT = seg(frame, 15, 30);
  const statT = seg(frame, 20, 35);
  const ruleT = seg(frame, 18, 34);
  return (
    <AbsoluteFill>
      <H3Clip
        src="assets/video/h3_datacenter.mp4"
        zoomFrom={1.4286}
        zoomTo={1.5}
        dim={0.55}
        volume={0.15}
        durationInFrames={240}
      />
      {/* 左下矢量标题（bottom 340：让开字幕安全区 0–300）*/}
      <div
        style={{
          position: 'absolute',
          left: 140,
          bottom: 340,
          opacity: titleT,
          transform: `translateY(${(1 - titleT) * 18}px)`,
        }}
      >
        <div
          style={{
            fontFamily: FONT_SANS,
            fontSize: 44,
            fontWeight: 600,
            color: INK,
            letterSpacing: '0.01em',
          }}
        >
          双卡 A800 · TP=2 · 262K 上下文
        </div>
        <div
          style={{
            marginTop: 14,
            height: 6,
            width: 320,
            background: ACCENT,
            borderRadius: 3,
            transform: `scaleX(${ruleT})`,
            transformOrigin: 'left center',
          }}
        />
      </div>
      {/* 右下 stat */}
      <div
        style={{
          position: 'absolute',
          right: 140,
          bottom: 340,
          textAlign: 'right',
          opacity: statT,
          transform: `translateY(${(1 - statT) * 18}px)`,
        }}
      >
        <div
          style={{
            fontFamily: FONT_SANS,
            fontSize: 26,
            color: MUTED,
            letterSpacing: '0.08em',
          }}
        >
          上线当天吞吐
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'flex-end', gap: 12 }}>
          <span
            style={{
              fontFamily: FONT_SANS,
              fontSize: 96,
              fontWeight: 800,
              color: '#FFFFFF',
              fontVariantNumeric: 'tabular-nums',
              lineHeight: 1.05,
            }}
          >
            46.5
          </span>
          <span style={{ fontFamily: FONT_SANS, fontSize: 30, color: MUTED }}>tok/s</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── s3 · hatch-depth（420–660f）─────────────────────────────────────────────
// 斜纹占位条逐条 wipe 伸长 → 斜纹淡出/实心淡入（几何零跳变）→ 数值弹出。
// 双柱对比 MTP 关 46.5 vs 开 75 tok/s；落定后静止 hold（R1）。
const S3_BARS = [
  { label: 'MTP 关', v: 46.5, dim: true },
  { label: 'MTP 开', v: 75, dim: false },
];

const Scene3HatchBars: React.FC = () => {
  const frame = useCurrentFrame();
  const headT = seg(frame, 5, 20);
  const noteT = seg(frame, 140, 160);
  const MAXV = 75;
  const FULLW = 1150;
  return (
    <AbsoluteFill style={{ backgroundColor: BG }}>
      {/* 顶部行：坑位标签 */}
      <div
        style={{
          position: 'absolute',
          left: 140,
          top: 120,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          opacity: headT,
          transform: `translateY(${(1 - headT) * 20}px)`,
        }}
      >
        <div style={{ width: 14, height: 14, borderRadius: 7, background: WARN }} />
        <span style={{ fontFamily: FONT_MONO_CJK, fontSize: 30, color: MUTED, letterSpacing: '0.06em' }}>
          坑 1 / MTP 静默失效
        </span>
      </div>
      {/* 柱状图 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 300,
          width: W,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 64,
        }}
      >
        {S3_BARS.map((bar, i) => {
          const grow = seg(frame, 15 + i * 12, 68 + i * 12);
          const morph = seg(frame, 90 + i * 12, 124 + i * 12);
          const wig = 1 + Math.sin(frame * 0.5 + i * 2.1) * 0.02 * seg(frame, 150, 180);
          const wPct = `${((bar.v / MAXV) * (FULLW / W) * 100 * grow * wig).toFixed(3)}%`;
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 32, width: 1560 }}>
              <div
                style={{
                  width: 320,
                  textAlign: 'right',
                  fontFamily: FONT_MONO_CJK,
                  fontSize: 36,
                  color: MUTED,
                }}
              >
                {bar.label}
              </div>
              <div style={{ position: 'relative', height: 130, width: FULLW }}>
                {/* 斜纹占位层 */}
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    height: '100%',
                    width: wPct,
                    borderRadius: 4,
                    background: 'repeating-linear-gradient(45deg,#565860 0 4px,transparent 4px 9px)',
                    border: '1px solid #565860',
                    opacity: 1 - morph,
                  }}
                />
                {/* 实心层（宽度共用同一条 grow 曲线，零几何跳变）*/}
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    height: '100%',
                    width: wPct,
                    borderRadius: 4,
                    background: bar.dim
                      ? '#3A4354'
                      : `linear-gradient(90deg,${ACCENT},${ACCENT_HI})`,
                    opacity: morph,
                  }}
                />
                {/* 柱端数值 */}
                <span
                  style={{
                    position: 'absolute',
                    left: `calc(${wPct} + 16px)`,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    fontFamily: FONT_SANS,
                    fontSize: 42,
                    fontWeight: 700,
                    color: bar.dim ? MUTED : ACCENT_HI,
                    fontVariantNumeric: 'tabular-nums',
                    whiteSpace: 'nowrap',
                    opacity: morph,
                  }}
                >
                  {bar.v} tok/s
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {/* 注释行（top 700：让开字幕安全区）*/}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 700,
          width: W,
          display: 'flex',
          justifyContent: 'center',
          opacity: noteT,
          transform: `translateY(${(1 - noteT) * 16}px)`,
        }}
      >
        <div
          style={{
            border: `2px solid ${WARN}`,
            borderRadius: 12,
            padding: '16px 34px',
            fontFamily: FONT_SANS,
            fontSize: 34,
            fontWeight: 600,
            color: WARN,
          }}
        >
          start.sh 丢了续航符 → MTP 静默失效
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── s4/s6 · paper-title-card（660–720f / 1020–1080f）────────────────────────
// 一句话逐词压印上纸、一词标强调色斜体、短划线收束（呼吸位）。
// 参数化：tokens/sub 换文案；全片两张字卡统一 60f（≈2s）定式。
const PaperCard: React.FC<{
  tokens: { t: string; mono?: boolean; accent?: boolean }[];
  sub: string;
}> = ({ tokens, sub }) => {
  const frame = useCurrentFrame();
  const fadeOut = interpolate(frame, [52, 60], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const underline = seg(frame, 16, 34);
  const subT = seg(frame, 24, 36);
  return (
    <AbsoluteFill
      style={{
        backgroundColor: PAPER,
        backgroundImage:
          'radial-gradient(1100px 750px at 50% 42%, rgba(255,252,244,0.9), transparent 65%)',
        justifyContent: 'center',
        alignItems: 'center',
        opacity: fadeOut,
      }}
    >
      <div style={{ textAlign: 'center', maxWidth: 1600 }}>
        <div
          style={{
            fontFamily: FONT_SERIF,
            fontSize: 100,
            fontWeight: 600,
            lineHeight: 1.2,
            color: PAPER_INK,
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'center',
            columnGap: '0.22em',
            rowGap: '0.15em',
          }}
        >
          {tokens.map((w, i) => {
            const delay = 4 + i * 4;
            const t = seg(frame, delay, delay + 9);
            return (
              <span
                key={i}
                style={{
                  opacity: t,
                  transform: `scale(${1.28 - 0.28 * t})`,
                  filter: `blur(${(1 - t) * 7}px)`,
                  display: 'inline-block',
                  fontStyle: w.accent ? 'italic' : 'normal',
                  color: w.accent ? AMBER_DARK : undefined,
                  fontFamily: w.mono ? FONT_MONO : undefined,
                  fontWeight: w.mono ? 600 : undefined,
                }}
              >
                {w.t}
              </span>
            );
          })}
        </div>
        <div
          style={{
            height: 6,
            width: 220,
            margin: '40px auto 0',
            borderRadius: 3,
            background: AMBER_DARK,
            transform: `scaleX(${underline})`,
          }}
        />
        <div
          style={{
            fontFamily: FONT_MONO,
            fontSize: 24,
            letterSpacing: '0.14em',
            color: PAPER_MUTED,
            marginTop: 30,
            opacity: subT,
            textTransform: 'uppercase',
          }}
        >
          {sub}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── s5 · typewriter-moves（A 式，720–1020f）─────────────────────────────────
// 终端风 start.sh 逐字敲出（1.8f/字符，帧确定 substring），方块光标方波闪；
// 敲完两面高亮旗（--enable-prefix-caching / --enable-prompt-tokens-details）
// 落位；底部旁白条滑入；落定 hold ≥1s（R1）。
const S5_LINES = [
  '$ vllm serve Qwen3.8-27B \\',
  '  --tensor-parallel-size 2 \\',
  '  --enable-prefix-caching \\',
  '  --enable-prompt-tokens-details',
];
const S5_FULL = S5_LINES.join('\n');
const S5_HERO = new Set([2, 3]); // 高亮旗行号

const Scene5Terminal: React.FC = () => {
  const frame = useCurrentFrame();
  const chars = Math.min(S5_FULL.length, Math.floor(Math.max(0, frame) / 1.8));
  const typed = S5_FULL.substring(0, chars);
  const typedLines = typed.split('\n');
  const done = chars >= S5_FULL.length;
  const cursorOn = frame % 12 < 6;
  const hiT = seg(frame, 232, 248); // 高亮旗落位
  const noteT = seg(frame, 252, 268); // 旁白条

  return (
    <AbsoluteFill
      style={{
        backgroundColor: BG,
        backgroundImage:
          'radial-gradient(1400px 900px at 50% 30%, rgba(30,41,59,0.5), transparent 70%)',
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <div
        style={{
          width: 1500,
          background: PANEL,
          borderRadius: 16,
          border: `1px solid ${LINE}`,
          boxShadow: '0 40px 100px rgba(0,0,0,0.6)',
          overflow: 'hidden',
        }}
      >
        {/* 标题栏 */}
        <div
          style={{
            height: 64,
            background: '#161C26',
            borderBottom: `1px solid ${LINE}`,
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            padding: '0 28px',
          }}
        >
          {['#FF6058', '#FFBD2E', '#28CA42'].map((c) => (
            <div key={c} style={{ width: 18, height: 18, borderRadius: 9, background: c }} />
          ))}
          <span
            style={{
              margin: '0 auto',
              fontFamily: FONT_MONO,
              fontSize: 24,
              color: MUTED,
            }}
          >
            start.sh
          </span>
          <span style={{ width: 72 }} />
        </div>
        {/* 内容区 */}
        <div style={{ padding: '40px 44px 48px', minHeight: 460 }}>
          {S5_LINES.map((line, li) => {
            const typedLine = typedLines[li] ?? '';
            const isHero = S5_HERO.has(li);
            const heroOn = isHero && done;
            return (
              <div
                key={li}
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: 36,
                  lineHeight: 1.65,
                  whiteSpace: 'pre',
                  color: heroOn ? ACCENT_HI : INK,
                  background: heroOn
                    ? `rgba(91,141,239,${0.16 * hiT})`
                    : 'transparent',
                  borderLeft: heroOn ? `4px solid rgba(91,141,239,${hiT})` : '4px solid transparent',
                  paddingLeft: 12,
                  marginLeft: -16,
                  borderRadius: 4,
                }}
              >
                {typedLine}
                {li === typedLines.length - 1 && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: 20,
                      height: 42,
                      marginLeft: 4,
                      background: INK,
                      opacity: cursorOn ? 1 : 0,
                      verticalAlign: '-6px',
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
      {/* 旁白条（top 200：窗口居中占 y330–755、字幕安全区在底部，挂顶部最干净）*/}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 200,
          width: W,
          display: 'flex',
          justifyContent: 'center',
          opacity: noteT,
          transform: `translateY(${(1 - noteT) * -16}px)`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 18,
            background: 'rgba(10,14,20,0.75)',
            border: `1px solid ${AMBER}`,
            borderRadius: 12,
            padding: '18px 36px',
          }}
        >
          <span
            style={{
              fontFamily: FONT_SANS,
              fontSize: 32,
              fontWeight: 700,
              color: AMBER,
            }}
          >
            cached_tokens？
          </span>
          <span style={{ fontFamily: FONT_SANS, fontSize: 32, fontWeight: 600, color: INK }}>
            vLLM 默认不返回
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── s7 · glow-flyline-moves（1080–1320f）────────────────────────────────────
// H3 光流 full-bleed 缓推 + 压暗 0.55；三块矢量 stat 芯片错峰浮入（底噪呼吸感
// 由 H3 素材本身的光斑承担，矢量层只做三枚芯片 + 一道脉冲飞线）。
const S7_STATS = [
  { label: '显存利用', value: '0.85 → 0.90' },
  { label: 'KV 池', value: '334K token' },
  { label: '并发', value: '4.43 → 4.87' },
];

const Scene7H3Lightflow: React.FC = () => {
  const frame = useCurrentFrame();
  const pulseT = seg(frame, 45, 80);
  return (
    <AbsoluteFill>
      <H3Clip
        src="assets/video/h3_lightflow.mp4"
        zoomFrom={1.4286}
        zoomTo={1.5}
        dim={0.55}
        volume={0.15}
        durationInFrames={240}
      />
      {/* 三枚 stat 芯片（bottom 350：让开字幕安全区）*/}
      <div
        style={{
          position: 'absolute',
          left: 0,
          bottom: 350,
          width: W,
          display: 'flex',
          justifyContent: 'center',
          gap: 56,
        }}
      >
        {S7_STATS.map((s, i) => {
          const t = seg(frame, 15 + i * 15, 35 + i * 15);
          return (
            <div
              key={i}
              style={{
                background: 'rgba(10,14,20,0.62)',
                border: `1px solid ${LINE}`,
                borderRadius: 14,
                padding: '26px 44px',
                textAlign: 'center',
                backdropFilter: 'blur(4px)',
                opacity: t,
                transform: `translateY(${(1 - t) * 22}px)`,
              }}
            >
              <div style={{ fontFamily: FONT_SANS, fontSize: 24, color: MUTED, letterSpacing: '0.08em' }}>
                {s.label}
              </div>
              <div
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 52,
                  fontWeight: 800,
                  color: INK,
                  fontVariantNumeric: 'tabular-nums',
                  marginTop: 8,
                  whiteSpace: 'nowrap',
                }}
              >
                {s.value}
              </div>
            </div>
          );
        })}
      </div>
      {/* 脉冲飞线：一道横线 + 亮点左→右跑一趟（数据在流动）*/}
      <div
        style={{
          position: 'absolute',
          left: 360,
          bottom: 320,
          width: 1200,
          height: 2,
          background: LINE,
          opacity: pulseT,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 360,
          bottom: 316,
          width: 10,
          height: 10,
          borderRadius: 5,
          background: ACCENT_HI,
          boxShadow: '0 0 16px rgba(143,178,247,0.9)',
          opacity: pulseT,
          transform: `translateX(${pulseT * 1190}px)`,
        }}
      />
    </AbsoluteFill>
  );
};

// ─── s8 · terminal-3d（1320–1560f）───────────────────────────────────────────
// 三终端窗散布 3D 空间，相机逆变换窗间飞行（途中正弦拉远）；每到一窗打字机
// 敲命令、输出逐行滑入；距离聚焦（离焦窗降透明度/亮度 + 轻 blur）。红框标注
// 「误杀的是 fork 子进程」是本镜主角。
// 性能注记（远程软渲染实测）：曾用 K=2 反缩放（3840×2160 大层 + 每层 blur），
// 单帧 >28s 触发 Remotion 帧超时；改 K=1 原生分辨率 + blur ≤1.2px + 窗口
// 680×420 后单帧回到秒级——有意识的简化，已在 render_report 记录（aesthetic P 判例）。
const K = 1;

type Win = {
  pose: { x: number; y: number; z: number; ry: number };
  title: string;
  cmd: string;
  out: string[];
};

const S8_WINS: Win[] = [
  {
    pose: { x: -560, y: -40, z: -160, ry: 22 },
    title: 'pgrep — vllm',
    cmd: '$ pgrep -f vllm',
    out: ['12847  /opt/vllm serve Qwen3.8-27B', '12848  /opt/vllm serve Qwen3.8-27B', '12849  /opt/vllm serve (fork child)', '12901  /opt/vllm serve Qwen3.8-27B'],
  },
  {
    pose: { x: 180, y: 110, z: 120, ry: -14 },
    title: 'vllm :8000',
    cmd: '$ curl -s :8000/health',
    out: ['{"status": "ok"}', '$ curl -s :8000/v1/chat/completions', '{"choices": []}   (empty)'],
  },
  {
    pose: { x: 760, y: -130, z: -90, ry: -28 },
    title: 'vllm.log',
    cmd: '$ tail -f vllm.log',
    out: ['(log was cleared)', ''],
  },
];

// 两段飞行窗口（窗0→1、窗1→2）
const STEP: [number, number][] = [
  [0.3, 0.44],
  [0.64, 0.78],
];
const TYPE = [0.05, 0.47, 0.81];
const PK = ['x', 'y', 'z', 'ry'] as const;

const accKeys = (
  t: number,
  base: Record<string, number>,
  kfs: { at: [number, number]; to: Record<string, number> }[],
  ease: (x: number) => number,
): Record<string, number> => {
  const out: Record<string, number> = { ...base };
  let prev = base;
  for (const kf of kfs) {
    const u = interpolate(t, kf.at, [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: ease,
    });
    for (const k of PK) out[k] += u * (kf.to[k] - prev[k]);
    prev = kf.to;
  }
  return out;
};

const Scene8Terminal3D: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = 240;
  const t = frame / dur;
  const v = accKeys(
    t,
    S8_WINS[0].pose,
    [
      { at: STEP[0], to: S8_WINS[1].pose },
      { at: STEP[1], to: S8_WINS[2].pose },
    ],
    Easing.inOut(Easing.cubic),
  );
  let pull = 0;
  for (let i = 0; i < 2; i++) {
    const u = interpolate(t, STEP[i], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    pull += Math.sin(u * Math.PI) * 210;
  }
  const callT = seg(frame, 56, 76); // 红框标注（SFX ui-notify 钉 f1386 = local 66）

  return (
    <AbsoluteFill style={{ backgroundColor: '#07080E' }}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: W * K,
          height: H * K,
          transform: `scale(${1 / K})`,
          transformOrigin: 'top left',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: 'radial-gradient(120% 90% at 50% 0%,#141826,#07080E 70%)',
            perspective: `${1100 * K}px`,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              transformStyle: 'preserve-3d',
              transform: `translateZ(${(300 - pull) * K}px) rotateY(${-v.ry}deg) translate3d(${-v.x * K}px,${-v.y * K}px,${-v.z * K}px)`,
            }}
          >
            {S8_WINS.map((d, i) => {
              const p = d.pose;
              const focus = 1 - Math.min(1, Math.abs(v.x - p.x) / 420);
              const ty = interpolate(t, [TYPE[i], TYPE[i] + 0.09], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              const n = Math.floor(ty * d.cmd.length + 0.0001);
              const caretOp =
                ty >= 1
                  ? Math.floor(t * 26) % 2
                    ? 0.15
                    : 0.9
                  : Math.floor(t * 40) % 2
                    ? 0.35
                    : 1;
              return (
                <div
                  key={i}
                  style={{
                    position: 'absolute',
                    left: '50%',
                    top: '50%',
                    width: 680 * K,
                    height: 420 * K,
                    margin: `${-210 * K}px 0 0 ${-340 * K}px`,
                    borderRadius: 14 * K,
                    background: '#0E1017',
                    overflow: 'hidden',
                    boxShadow: `0 ${40 * K}px ${110 * K}px rgba(0,0,0,0.7), inset 0 0 0 ${2 * K}px #2A3040`,
                    transform: `translate3d(${p.x * K}px,${p.y * K}px,${p.z * K}px) rotateY(${p.ry}deg)`,
                    opacity: 0.34 + focus * 0.66,
                    filter: `blur(${(1 - focus) * 1.2 * K}px) brightness(${0.7 + focus * 0.3})`,
                  }}
                >
                  {/* 标题栏 */}
                  <div
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      width: '100%',
                      height: 48 * K,
                      background: 'linear-gradient(180deg,#242A38,#1B202B)',
                      borderBottom: `${2 * K}px solid #2C3242`,
                    }}
                  >
                    {['#FF6058', '#FFBD2E', '#28CA42'].map((c, k) => (
                      <div
                        key={c}
                        style={{
                          position: 'absolute',
                          left: (20 + k * 26) * K,
                          top: 16 * K,
                          width: 14 * K,
                          height: 14 * K,
                          borderRadius: 7 * K,
                          background: c,
                        }}
                      />
                    ))}
                    <div
                      style={{
                        position: 'absolute',
                        left: 0,
                        top: 0,
                        width: '100%',
                        height: 48 * K,
                        textAlign: 'center',
                        font: `600 ${18 * K}px/${48 * K}px ${FONT_MONO}`,
                        color: '#77809B',
                      }}
                    >
                      {d.title}
                    </div>
                  </div>
                  {/* 命令行 */}
                  <div
                    style={{
                      position: 'absolute',
                      left: 24 * K,
                      top: 72 * K,
                      font: `600 ${23 * K}px/1.4 ${FONT_MONO}`,
                      color: '#9DFFCF',
                      whiteSpace: 'pre',
                    }}
                  >
                    {d.cmd.substring(0, n)}
                    <span
                      style={{
                        display: 'inline-block',
                        color: '#9DFFCF',
                        opacity: caretOp,
                      }}
                    >
                      ▌
                    </span>
                  </div>
                  {/* 输出行 */}
                  {d.out.map((o, k) => {
                    const ou = interpolate(
                      t,
                      [TYPE[i] + 0.1 + k * 0.022, TYPE[i] + 0.135 + k * 0.022],
                      [0, 1],
                      { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) },
                    );
                    return (
                      <div
                        key={k}
                        style={{
                          position: 'absolute',
                          left: 24 * K,
                          top: (112 + k * 40) * K,
                          font: `500 ${20 * K}px/1.35 ${FONT_MONO}`,
                          color: k === 0 ? '#C9D3EA' : o.includes('empty') || o.includes('cleared') || o.includes('fork') ? WARN : '#7F8AA6',
                          whiteSpace: 'pre',
                          opacity: ou,
                          transform: `translateX(${(1 - ou) * -16 * K}px)`,
                        }}
                      >
                        {o}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {/* 红框标注（本镜主角，唯一红色；top 200 横幅，让开窗体与字幕安全区）*/}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 200,
          width: W,
          display: 'flex',
          justifyContent: 'center',
          opacity: callT,
          transform: `translateY(${(1 - callT) * -18}px)`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 18,
            background: 'rgba(20,6,8,0.78)',
            border: `2px solid ${WARN}`,
            borderRadius: 12,
            padding: '18px 36px',
            boxShadow: `0 0 40px rgba(229,72,77,${0.35 * callT})`,
          }}
        >
          <div
            style={{
              width: 22,
              height: 22,
              borderRadius: 11,
              background: WARN,
              flex: 'none',
            }}
          />
          <span style={{ fontFamily: FONT_SANS, fontSize: 36, fontWeight: 700, color: '#FFFFFF' }}>
            误杀的是 fork 子进程
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── s9 · odometer-digit-roll（1560–1740f）───────────────────────────────────
// 全屏巨号 75：两位滚轮独立纵滚带残影，逐位过冲半格锁定，全体锁定瞬间加深
// 脉冲；+60% 角标弹入；落定 hold ≥1s。hero 时刻：暖金底，不用 H3（768p 对策）。
const ROW = 340; // 数位行高
const DW = 210; // 数位盒宽
const FS = 300; // 字号
const SPIN = 0.85; // 高速滚动：行/帧
const DIGITS = [7, 5]; // 终值各位

const posAt = (f: number, i: number): number => {
  const d = DIGITS[i];
  const s = 20 + i * 7;
  const p0 = SPIN * s;
  const T = Math.ceil((p0 + 6 - d) / 10) * 10 + d;
  if (f < s) return SPIN * Math.max(f, 0);
  if (f < s + 16)
    return interpolate(f, [s, s + 16], [p0, T + 0.5], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    });
  if (f < s + 22)
    return interpolate(f, [s + 16, s + 22], [T + 0.5, T], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    });
  return T;
};

const Strip: React.FC<{ pos: number; color: string; opacity?: number; dy?: number }> = ({
  pos,
  color,
  opacity = 1,
  dy = 0,
}) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      top: 0,
      width: DW,
      transform: `translateY(${-(pos % 10) * ROW + dy}px)`,
      opacity,
    }}
  >
    {Array.from({ length: 12 }).map((_, k) => (
      <div
        key={k}
        style={{
          width: DW,
          height: ROW,
          lineHeight: `${ROW}px`,
          textAlign: 'center',
          fontSize: FS,
          fontWeight: 800,
          fontVariantNumeric: 'tabular-nums',
          color,
        }}
      >
        {k % 10}
      </div>
    ))}
  </div>
);

const DigitReel: React.FC<{ frame: number; i: number; color: string }> = ({ frame, i, color }) => {
  const pos = posAt(frame, i);
  const speed = Math.abs(pos - posAt(frame - 1, i));
  const gate = interpolate(speed, [0.06, 0.5], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div style={{ position: 'relative', width: DW, height: ROW, overflow: 'hidden' }}>
      {gate > 0.001 && (
        <>
          <Strip pos={pos} color={color} opacity={0.25 * gate} dy={ROW * 0.5} />
          <Strip pos={pos} color={color} opacity={0.12 * gate} dy={-ROW * 0.5} />
        </>
      )}
      <Strip pos={pos} color={color} />
    </div>
  );
};

const Scene9Odometer: React.FC = () => {
  const frame = useCurrentFrame();
  const inkNow = interpolateColorsSafe(frame, [49, 53, 57], ['#E8ECF3', '#000000', '#E8ECF3']);
  const pulseScale = interpolate(frame, [49, 53, 57], [1, 1.035, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.quad),
  });
  const badgeT = seg(frame, 55, 75);
  const labelT = seg(frame, 60, 80);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: BG,
        backgroundImage:
          'radial-gradient(1300px 850px at 50% 42%, rgba(242,193,78,0.12), transparent 70%)',
      }}
    >
      {/* 顶部小标签 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 120,
          width: W,
          textAlign: 'center',
          fontFamily: FONT_MONO_CJK,
          fontSize: 28,
          color: MUTED,
          letterSpacing: '0.1em',
          opacity: seg(frame, 8, 22),
        }}
      >
        修完三处 · 终态吞吐
      </div>
      {/* 巨号数字 */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 330,
          width: W,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'baseline',
          fontFamily: FONT_SANS,
          transform: `scale(${pulseScale})`,
          transformOrigin: '960px 170px',
        }}
      >
        <DigitReel frame={frame} i={0} color={inkNow} />
        <DigitReel frame={frame} i={1} color={inkNow} />
        <span
          style={{
            fontSize: 96,
            fontWeight: 600,
            color: MUTED,
            marginLeft: 24,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          tok/s
        </span>
      </div>
      {/* +60% 角标 */}
      <div
        style={{
          position: 'absolute',
          right: 200,
          top: 150,
          fontFamily: FONT_SANS,
          fontSize: 84,
          fontWeight: 800,
          color: GOLD,
          fontVariantNumeric: 'tabular-nums',
          opacity: badgeT,
          transform: `scale(${0.6 + 0.4 * badgeT})`,
          transformOrigin: 'right center',
          textShadow: '0 4px 30px rgba(242,193,78,0.35)',
        }}
      >
        +60%
      </div>
      {/* 下方说明（top 700：让开字幕安全区）*/}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 700,
          width: W,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 18,
          opacity: labelT,
        }}
      >
        <div style={{ width: 520, height: 3, background: LINE, borderRadius: 2 }} />
        <div style={{ fontFamily: FONT_SANS, fontSize: 40, fontWeight: 600, color: INK }}>
          贴近 2×A800 带宽墙
        </div>
      </div>
    </AbsoluteFill>
  );
};

// interpolateColors 的薄封装（clamp 版：该版本 options 不含 extrapolate 字段）
const interpolateColorsSafe = (
  frame: number,
  range: number[],
  colors: string[],
): string => {
  const lo = range[0];
  const hi = range[range.length - 1];
  const fc = Math.max(lo, Math.min(hi, frame));
  return interpolateColors(fc, range, colors);
};

// ─── s10 · outro-group-photo-launch（峰值收场，1740–1920f）───────────────────
// H3 金粒 full-bleed（原声压 0.15 让旁白，与 s2/s7 同规）+ 压暗 0.55 +
// 三条教训清单逐条压印 + sign-off hold。金尘 20 颗确定性上飘（全参数 index
// 派生）。能量全片峰值。
const LESSONS = ['参数要核对', '指标要验证', '重启要认得主进程'];

const DUST = Array.from({ length: 20 }, (_, i) => ({
  x: (i * 439 + 137) % W,
  y0: 1150 + ((i * 613 + 271) % 200),
  rise: 300 + (i % 5) * 45,
  sway: 10 + (i % 4) * 5,
  phase: (i * 0.83) % (Math.PI * 2),
  size: 4 + (i % 3) * 2,
  op: 0.15 + ((i * 7) % 5) * 0.05,
  delay: 15 + (i % 7) * 6,
}));

const Scene10Finale: React.FC = () => {
  const frame = useCurrentFrame();
  const signT = seg(frame, 100, 118);
  // H3 原声压 0.15 让旁白（s10 按脚本定稿有旁白），首尾 9f 淡化软化接缝
  const h3fade = interpolate(frame, [0, 9, 171, 180], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const h3vol = 0.15 * h3fade;
  return (
    <AbsoluteFill>
      <H3Clip
        src="assets/video/h3_finale.mp4"
        zoomFrom={1.4286}
        zoomTo={1.5}
        dim={0.55}
        volume={h3vol}
        durationInFrames={180}
      />
      {/* 金尘 */}
      {DUST.map((d, i) => {
        const life = seg(frame, d.delay, 180);
        if (life <= 0) return null;
        const y = d.y0 - d.rise * life;
        const x = d.x + Math.sin(frame * 0.045 + d.phase) * d.sway;
        const tw = 0.6 + 0.4 * Math.sin(frame * 0.08 + d.phase * 2);
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: d.size,
              height: d.size,
              borderRadius: d.size / 2,
              background: GOLD,
              opacity: d.op * life * tw,
              boxShadow: '0 0 8px rgba(242,193,78,0.6)',
            }}
          />
        );
      })}
      {/* 教训清单（左下角矢量层）*/}
      <div
        style={{
          position: 'absolute',
          left: 160,
          top: 250,
          display: 'flex',
          flexDirection: 'column',
          gap: 34,
        }}
      >
        <div
          style={{
            fontFamily: FONT_SERIF,
            fontSize: 26,
            fontWeight: 600,
            color: GOLD,
            letterSpacing: '0.16em',
            opacity: seg(frame, 4, 18),
          }}
        >
          三个教训
        </div>
        {LESSONS.map((lesson, i) => {
          const t = seg(frame, 14 + i * 16, 30 + i * 16);
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 26,
                opacity: t,
                transform: `translateX(${(1 - t) * -30}px)`,
              }}
            >
              <span
                style={{
                  fontFamily: FONT_SERIF,
                  fontSize: 34,
                  fontWeight: 600,
                  color: GOLD,
                  border: `2px solid rgba(242,193,78,0.6)`,
                  borderRadius: 10,
                  padding: '4px 16px',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                0{i + 1}
              </span>
              <span
                style={{
                  fontFamily: FONT_SANS,
                  fontSize: 52,
                  fontWeight: 600,
                  color: INK,
                  textShadow: '0 2px 16px rgba(0,0,0,0.6)',
                }}
              >
                {lesson}
              </span>
            </div>
          );
        })}
      </div>
      {/* sign-off（hold ≥1s：118f 落定 → 180f 结束；bottom 330 让开字幕安全区）*/}
      <div
        style={{
          position: 'absolute',
          left: 0,
          bottom: 330,
          width: W,
          textAlign: 'center',
          fontFamily: FONT_SERIF,
          fontSize: 32,
          color: '#D8D2C4',
          letterSpacing: '0.08em',
          opacity: signT,
        }}
      >
        Qwen3.8-27B 部署踩坑记 · 完
      </div>
    </AbsoluteFill>
  );
};

// ─── 时间线 ──────────────────────────────────────────────────────────────────
// 场景边界（帧）：s1 0-180 / s2 180-420 / s3 420-660 / s4 660-720 / s5 720-1020
// s6 1020-1080 / s7 1080-1320 / s8 1320-1560 / s9 1560-1740 / s10 1740-1920
// 转场（scene_plan）：s1 -/fade, s2 fade/fade, s3 fade/cut, s4 cut/fade,
// s5 fade/cut, s6 cut/fade, s7 fade/fade, s8 fade/cut, s9 cut/fade, s10 fade/none
const Main: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: BG }}>
      <style>{FONT_CSS}</style>
      <FontGate />

      <SceneShell from={0} durationInFrames={180} fadeIn={0} fadeOut={9}>
        <Scene1BrandInk />
      </SceneShell>
      <SceneShell from={180} durationInFrames={240} fadeIn={9} fadeOut={9}>
        <Scene2H3Datacenter />
      </SceneShell>
      <SceneShell from={420} durationInFrames={240} fadeIn={9} fadeOut={0}>
        <Scene3HatchBars />
      </SceneShell>
      <SceneShell from={660} durationInFrames={60} fadeIn={0} fadeOut={9}>
        <PaperCard
          tokens={[
            { t: '续航' },
            { t: '一丢，' },
            { t: 'MTP', mono: true },
            { t: '静默失效', accent: true },
          ]}
          sub="breather · pit 1 recap"
        />
      </SceneShell>
      <SceneShell from={720} durationInFrames={300} fadeIn={9} fadeOut={0}>
        <Scene5Terminal />
      </SceneShell>
      <SceneShell from={1020} durationInFrames={60} fadeIn={0} fadeOut={9}>
        <PaperCard
          tokens={[
            { t: '66.7%', mono: true },
            { t: '命中，' },
            { t: 'API', mono: true },
            { t: '却不吐' },
            { t: 'cached_tokens', mono: true, accent: true },
          ]}
          sub="breather · pit 2 recap"
        />
      </SceneShell>
      <SceneShell from={1080} durationInFrames={240} fadeIn={9} fadeOut={9}>
        <Scene7H3Lightflow />
      </SceneShell>
      <SceneShell from={1320} durationInFrames={240} fadeIn={9} fadeOut={0}>
        <Scene8Terminal3D />
      </SceneShell>
      <SceneShell from={1560} durationInFrames={180} fadeIn={0} fadeOut={9}>
        <Scene9Odometer />
      </SceneShell>
      <SceneShell from={1740} durationInFrames={180} fadeIn={9} fadeOut={0}>
        <Scene10Finale />
      </SceneShell>

      <SpeakerBadges />
      <Subtitles />

      {/* 音频：BGM 包络 */}
      <Audio
        src={staticFile('assets/audio/bgm/bgm-tech-house.mp3')}
        volume={(f) => BGM_ENVELOPE[Math.max(0, Math.min(DURATION, f))]}
      />
      {/* 旁白（s10 按复核结论无旁白）*/}
      {NARRATION.map((n, i) => (
        <Sequence key={`narr-${i}`} from={n.from} durationInFrames={n.dur} name={`narration@${n.from}`}>
          <Audio src={staticFile(n.src)} />
        </Sequence>
      ))}
      {/* SFX 钉帧表 */}
      {SFX.map((s, i) => (
        <Sequence key={`sfx-${i}`} from={s.from} durationInFrames={s.dur} name={`sfx:${s.note}`}>
          <Audio src={staticFile(s.src)} volume={s.vol} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Qwen38Deploy"
    component={Main}
    durationInFrames={DURATION}
    fps={FPS}
    width={W}
    height={H}
  />
);

registerRoot(RemotionRoot);
