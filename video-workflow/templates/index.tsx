// 讲解视频（单人/双人通用）— Remotion atelier 工程模板
// 用法：复制到项目，改 DURATION / NARRATION / SFX / SUBTITLES / 各 Scene 组件。
// 确定性渲染：禁 Date.now()/Math.random()，伪随机用 h()。转场只用 {fade,cut,none}。
//
// 六条铁律（违反 = 黑屏/豆腐块/动画缺失，全部实战踩过，详见 SKILL.md §2⑥）：
// 1. 场景必须包 SceneShell（内部 SceneFade 子组件在 Sequence 内取相对帧）；
//    禁止在 Sequence 外的 IIFE 里调 useCurrentFrame（取到全局帧 → 除第一景外全黑）。
// 2. 场景内延迟入场叠加层必须写在组件里（Reveal/Tag/Stamp）；禁止内联 opacity: seg(0,…)。
// 3. 禁 emoji（渲染机无彩色 emoji 字体 → 豆腐块）；用汉字/CSS 图形。
// 4. 含中文文本禁裸 mono 链；混排用 '"DejaVu Sans Mono","Noto Sans SC",monospace'。
// 5. 全局动效层（EmberField）+ 每景至少一个持续动画；关键信息落定 hold ≥1s。
// 6. 底部 260px 留给字幕，场景文字别压进来。
import React, { useEffect, useState } from 'react';
import {
  AbsoluteFill, Audio, Composition, OffthreadVideo, Sequence,
  Easing, interpolate, registerRoot, spring, staticFile, useCurrentFrame,
  delayRender, continueRender,
} from 'remotion';

// ─── 常量（按项目改）─────────────────────────────────────────────
const FPS = 30;
const W = 1920;
const H = 1080;
const DURATION = 1920; // 总帧数 = 秒数 × 30

const FONT_SANS = '"Noto Sans SC", sans-serif';
const FONT_SERIF = '"Noto Serif SC", serif';
const FONT_MONO = '"DejaVu Sans Mono", Menlo, Consolas, monospace';

// 色板（暗科技风；按 art-direction 改）
const BG = '#0A0E14';
const INK = '#E8ECF3';
const MUTED = '#8B93A5';
const ACCENT = '#5B8DEF';
const GOLD = '#F2C14E';

// 双人说话人配色（固定，别改）
const SPK_COLOR = { X: '#F472B6' /* 晓晓粉 */, Y: '#5B8DEF' /* 云希蓝 */ } as const;
const SPK_NAME = { X: '晓晓', Y: '云希' } as const;
type Speaker = keyof typeof SPK_COLOR;

// 固定种子伪随机
const h = (n: number): number => {
  const s = Math.sin(n * 127.3) * 43758.5453;
  return s - Math.floor(s);
};
const seg = (f: number, a: number, b: number): number =>
  interpolate(f, [a, b], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

// ─── 字体（渲染机无 CJK 系统字体，从 public/fonts 加载）─────────────
const FONT_CSS = `
@font-face { font-family:'Noto Sans SC'; src:url('${staticFile('fonts/NotoSansSC-VF.ttf')}') format('truetype'); font-weight:100 900; font-display:block; }
@font-face { font-family:'Noto Serif SC'; src:url('${staticFile('fonts/NotoSerifSC-VF.ttf')}') format('truetype'); font-weight:100 900; font-display:block; }
`;
const FontGate: React.FC = () => {
  const [handle] = useState(() => delayRender('font-load'));
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const fa = (document as unknown as { fonts: FontFaceSet }).fonts;
        await Promise.all([
          fa.load('500 100px "Noto Sans SC"'), fa.load('700 100px "Noto Sans SC"'),
          fa.load('600 100px "Noto Serif SC"'),
        ]);
        await fa.ready;
      } catch { /* fallback 系统字体，抽帧会发现豆腐块 */ }
      finally { if (alive) continueRender(handle); }
    })();
    return () => { alive = false; };
  }, [handle]);
  return null;
};

// ─── 三张时间线表（每项目填这些）──────────────────────────────────
// 旁白：from/dur 帧，src 相对 public（wav 由 make_duo_tts.py 生成）
const NARRATION: { from: number; dur: number; src: string }[] = [
  // { from: 12, dur: 80, src: 'assets/audio/narration/s1.wav' },
];
// SFX 钉帧（由 make_sfx.py 生成后整段替换；素材按事件名在 public/assets/audio/sfx/）
const SFX: { from: number; dur: number; src: string; vol: number; note?: string }[] = [];
// 字幕：每句带说话人，时间从 timing.json 换算（段起点帧 + start*30）
interface Cue { from: number; to: number; spk: Speaker; lines: string[] }
const SUBTITLES: Cue[] = [
  // { from: 12, to: 90, spk: 'X', lines: ['开场句'] },
];

// BGM 包络：0.34 铺底 + 旁白段 ducking（按需改窗口）
const DUCK_WINDOWS: [number, number, number][] = [];
const BGM_ENVELOPE: number[] = (() => {
  const arr = new Array(DURATION + 1);
  for (let f = 0; f <= DURATION; f++) {
    let v = interpolate(f, [0, 45], [0, 0.34], { extrapolateRight: 'clamp' });
    for (const [a, b, t] of DUCK_WINDOWS) {
      if (f >= a && f <= b) {
        const g = Math.min(seg(f, a, a + 6), 1 - seg(f, b - 24, b));
        v = Math.min(v, 0.34 - (0.34 - t) * g);
      }
    }
    v *= interpolate(f, [DURATION - 60, DURATION], [1, 0], { extrapolateLeft: 'clamp' });
    arr[f] = v;
  }
  return arr;
})();

// ─── 共用组件 ─────────────────────────────────────────────────────

// 场景壳：fade/cut 在时间线层兑现
// SceneFade 必须是真组件：在 Sequence 内 useCurrentFrame 才取相对帧。
// 禁止在 SceneShell 里用 IIFE 调 useCurrentFrame（取到全局帧 → 除第一景外全部黑屏）。
const SceneShell: React.FC<{ from: number; durationInFrames: number; fadeIn: number; fadeOut: number; children: React.ReactNode }> =
  ({ from, durationInFrames, fadeIn, fadeOut, children }) => (
    <Sequence from={from} durationInFrames={durationInFrames} name={`scene@${from}`}>
      <SceneFade fadeIn={fadeIn} fadeOut={fadeOut} durationInFrames={durationInFrames}>
        {children}
      </SceneFade>
    </Sequence>
  );

const SceneFade: React.FC<{ fadeIn: number; fadeOut: number; durationInFrames: number; children: React.ReactNode }> =
  ({ fadeIn, fadeOut, durationInFrames, children }) => {
    const frame = useCurrentFrame();
    const opacity = interpolate(
      frame, [0, Math.max(fadeIn, 0.001), durationInFrames - Math.max(fadeOut, 0.001), durationInFrames],
      [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
    return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
  };

// H3 素材 full-bleed cover + Ken Burns + 压暗（768p 对策）
// zoomFrom 默认 1.15：H3 生成素材底缘常有模型烙印文字（no text 不保险），基础放大 ≥1.2 可裁掉；
// qa_check.py 会输出每条素材的底缘条带图，确认干净可改回 1.0。
// ⚠️ 素材时长 < 窗口时长时必须传 playbackRate=素材秒/窗口秒（如 5s 素材进 8s 窗口传 0.65），
// 否则素材播完后画面定格；探针抽帧看不出，要用首尾帧像素差验证（09-13 戒糖片坑）。
const H3Clip: React.FC<{ src: string; zoomFrom?: number; zoomTo?: number; dim?: number; volume?: number | ((f: number) => number); durationInFrames: number }> =
  ({ src, zoomFrom = 1.15, zoomTo = 1.22, dim = 0.55, volume = 0, durationInFrames }) => {
    const frame = useCurrentFrame();
    const zoom = interpolate(frame, [0, durationInFrames], [zoomFrom, zoomTo], { extrapolateRight: 'clamp' });
    return (
      <AbsoluteFill style={{ backgroundColor: '#05070B' }}>
        <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: 'center', overflow: 'hidden' }}>
          <OffthreadVideo src={staticFile(src)} volume={volume}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </AbsoluteFill>
        <AbsoluteFill style={{ backgroundColor: `rgba(6,10,16,${dim})` }} />
      </AbsoluteFill>
    );
  };

// 大数字 stat 卡
const StatCard: React.FC<{ value: string; label?: string; accent?: string; size?: number }> =
  ({ value, label, accent = GOLD, size = 120 }) => (
    <div style={{ textAlign: 'center', color: INK }}>
      <div style={{ fontFamily: FONT_MONO, fontWeight: 800, fontSize: size, color: accent,
        textShadow: `0 0 40px ${accent}66` }}>{value}</div>
      {label && <div style={{ fontFamily: FONT_SANS, fontSize: 34, color: MUTED, marginTop: 12 }}>{label}</div>}
    </div>
  );

// 延迟入场文字层（标准叠加件）：真组件、取 Sequence 内相对帧。
// 场景内一切延迟动画都用它或 Tag/Stamp——禁止内联 opacity: seg(0,…)（帧号写死 0 永不显示）。
const Reveal: React.FC<{ delay: number; dur?: number; rise?: number; style?: React.CSSProperties; children: React.ReactNode }> =
  ({ delay, dur = 20, rise = 26, style, children }) => {
    const frame = useCurrentFrame();
    const p = seg(frame, delay, delay + dur);
    if (frame < delay) return null;
    return (
      <div style={{ ...style, opacity: p, transform: `${style?.transform ?? ''} translateY(${(1 - p) * rise}px)`.trim() }}>
        {children}
      </div>
    );
  };

// 弹入标签（Tag）：H3 场景上的浮层信息条
const Tag: React.FC<{ text: string; color?: string; delay?: number; x?: number | string; y?: number | string; size?: number }> =
  ({ text, color = GOLD, delay = 0, x = '50%', y = '50%', size = 34 }) => {
    const frame = useCurrentFrame();
    const pop = spring({ frame: frame - delay, fps: FPS, config: { damping: 12, stiffness: 160, mass: 0.6 } });
    if (frame < delay) return null;
    return (
      <div style={{ position: 'absolute', left: x, top: y, transform: `translate(-50%,-50%) scale(${pop})`,
        fontFamily: FONT_SANS, fontWeight: 800, fontSize: size, color: INK,
        backgroundColor: 'rgba(10,13,20,0.78)', border: `2px solid ${color}`, borderRadius: 12,
        padding: '10px 26px', boxShadow: `0 0 30px ${color}44`, whiteSpace: 'nowrap' }}>
        {text}
      </div>
    );
  };

// 落章大字（Stamp）：带震动
const Stamp: React.FC<{ text: string; color?: string; delay?: number; size?: number; serif?: boolean; y?: string }> =
  ({ text, color = ACCENT, delay = 0, size = 190, serif = false, y = '44%' }) => {
    const frame = useCurrentFrame();
    const pop = spring({ frame: frame - delay, fps: FPS, config: { damping: 10, stiffness: 120, mass: 0.9 } });
    const shake = frame >= delay && frame < delay + 6 ? Math.sin(frame * 2.2) * (6 - (frame - delay)) : 0;
    if (frame < delay) return null;
    return (
      <div style={{ position: 'absolute', left: '50%', top: y, transform: `translate(-50%,-50%) translateX(${shake}px) scale(${0.6 + 0.4 * pop})`,
        fontFamily: serif ? FONT_SERIF : FONT_SANS, fontWeight: 900, fontSize: size, color,
        textShadow: `0 0 60px ${color}88`, letterSpacing: 8, whiteSpace: 'nowrap' }}>
        {text}
      </div>
    );
  };

// 全局余烬粒子层（"持续动画"的基底，挂在 Main 最上层）
const EmberField: React.FC = () => {
  const frame = useCurrentFrame();
  const embers = [];
  for (let i = 0; i < 36; i++) {
    const speed = 14 + h(i * 3 + 1) * 34;
    const x = h(i * 7 + 2) * W;
    const drift = 30 + h(i * 11 + 3) * 60;
    const size = 2 + h(i * 13 + 4) * 5;
    const y = H + 60 - ((frame * speed / 30 + h(i * 17 + 5) * (H + 120)) % (H + 160));
    const xOff = Math.sin(frame * 0.02 + i * 1.7) * drift;
    const flick = Math.max(0, (0.35 + 0.3 * Math.sin(frame * 0.09 + i * 2.3)) * 0.55);
    embers.push(
      <div key={i} style={{ position: 'absolute', left: x + xOff, top: y, width: size, height: size, borderRadius: '50%',
        background: GOLD, opacity: flick, boxShadow: `0 0 ${size * 3}px ${GOLD}` }} />
    );
  }
  return <AbsoluteFill style={{ pointerEvents: 'none', zIndex: 5 }}>{embers}</AbsoluteFill>;
};

// 顶部进度条（持续微动画）
const ProgressHair: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: 'absolute', top: 0, left: 0, height: 5, width: `${(frame / DURATION) * 100}%`,
      background: `linear-gradient(90deg, ${ACCENT}, ${GOLD})`, zIndex: 8, opacity: 0.85 }} />
  );
};

// 说话人角标（左下，谁说话谁亮）
const SpeakerBadges: React.FC = () => {
  const frame = useCurrentFrame();
  const cue = SUBTITLES.find((s) => frame >= s.from && frame < s.to);
  const active = cue?.spk ?? null;
  const Avatar = ({ spk, glyph }: { spk: Speaker; glyph: string }) => {
    const isActive = active === spk;
    const color = SPK_COLOR[spk];
    const scale = isActive
      ? interpolate(frame, [cue!.from, cue!.from + 6], [0.85, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.back(1.5)) })
      : 1;
    const glow = isActive ? 0.5 + 0.15 * Math.sin(frame * 0.18) : 0;
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 14,
        opacity: active === null ? 0.55 : isActive ? 1 : 0.35, transform: `scale(${scale})` }}>
        <div style={{ width: 84, height: 84, borderRadius: '50%',
          background: `radial-gradient(circle at 35% 30%, ${color}33, ${color}14)`,
          border: `3px solid ${color}`,
          boxShadow: isActive ? `0 0 ${24 + glow * 30}px ${color}${Math.round(glow * 180).toString(16).padStart(2, '0')}` : 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: FONT_SANS, fontWeight: 800, fontSize: 40, color }}>{glyph}</div>
        <div style={{ fontFamily: FONT_SANS, fontWeight: 700, fontSize: 30,
          color: isActive ? color : MUTED }}>{SPK_NAME[spk]}</div>
      </div>
    );
  };
  return (
    <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'flex-start', paddingLeft: 80, paddingBottom: 110, pointerEvents: 'none' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <Avatar spk="X" glyph="晓" />
        <Avatar spk="Y" glyph="希" />
      </div>
    </AbsoluteFill>
  );
};

// 字幕：贴底、小字号、按说话人着色
const Subtitles: React.FC = () => {
  const frame = useCurrentFrame();
  const cue = SUBTITLES.find((s) => frame >= s.from && frame < s.to);
  if (!cue) return null;
  const opacity = interpolate(frame, [cue.from, cue.from + 4, cue.to - 4, cue.to], [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const color = SPK_COLOR[cue.spk];
  return (
    <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 48, pointerEvents: 'none' }}>
      <div style={{ opacity, maxWidth: 1500, textAlign: 'center' }}>
        <div style={{ display: 'inline-block', backgroundColor: 'rgba(0,0,0,0.55)', borderRadius: 8,
          padding: '5px 18px 7px', marginBottom: 8, borderLeft: `4px solid ${color}`,
          fontFamily: FONT_SANS, fontWeight: 700, fontSize: 30, color, letterSpacing: 2 }}>
          {SPK_NAME[cue.spk]}
        </div>
        {cue.lines.map((l, i) => (
          <div key={i} style={{ fontFamily: FONT_SANS, fontWeight: 600, fontSize: 42, lineHeight: 1.3,
            color: '#FFF', WebkitTextStroke: '2px rgba(0,0,0,0.9)', paintOrder: 'stroke fill',
            textShadow: '0 2px 10px rgba(0,0,0,0.7)' }}>{l}</div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ─── 场景组件（按项目写，下面是占位示例）────────────────────────────
const Scene1Open: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: BG, justifyContent: 'center', alignItems: 'center' }}>
    <StatCard value="200万" label="美元/年" size={140} />
  </AbsoluteFill>
);

// ─── 时间线（按项目排 SceneShell）──────────────────────────────────
const Main: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: BG }}>
    <style>{FONT_CSS}</style>
    <FontGate />

    {/* 示例：
    <SceneShell from={0} durationInFrames={180} fadeIn={0} fadeOut={9}><Scene1Open /></SceneShell>
    <SceneShell from={180} durationInFrames={240} fadeIn={9} fadeOut={9}>
      <H3Clip src="assets/video/h3_1.mp4" durationInFrames={240} />
    </SceneShell>
    */}

    <SpeakerBadges />
    <Subtitles />

    {/* BGM（按需）：
    <Audio src={staticFile('assets/audio/bgm/bgm.mp3')} volume={(f) => BGM_ENVELOPE[f]} />
    */}
    {NARRATION.map((n, i) => (
      <Sequence key={i} from={n.from} durationInFrames={n.dur} name={`narration@${n.from}`}>
        <Audio src={staticFile(n.src)} />
      </Sequence>
    ))}
    {SFX.map((s, i) => (
      <Sequence key={i} from={s.from} durationInFrames={s.dur} name={`sfx:${s.note ?? i}`}>
        <Audio src={staticFile(s.src)} volume={s.vol} />
      </Sequence>
    ))}
  </AbsoluteFill>
);

export const RemotionRoot: React.FC = () => (
  <Composition id="Explainer" component={Main} durationInFrames={DURATION} fps={FPS} width={W} height={H} />
);
registerRoot(RemotionRoot);
