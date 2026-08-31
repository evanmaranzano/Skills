# Remotion 矢量组件实现要点

> 配套 `templates/index.tsx`。所有信息层（文字/数字/图表）都是矢量 React 组件，
> H3 只当 full-bleed B-roll。确定性渲染是硬规则。

## 核心 API

```tsx
import { useCurrentFrame, useVideoConfig, interpolate, spring, Easing, Sequence, AbsoluteFill, staticFile, Audio } from 'remotion';

const frame = useCurrentFrame();
// 进度 0→1（两端 clamp）
const p = interpolate(frame, [a, b], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
// 弹入
const s = spring({ frame, fps, config: { damping: 20, stiffness: 120 } });
```

## 时间换算
- 秒 × 30 = 帧；`DURATION = 总秒数 × 30`。
- 字幕 from/to、NARRATION 的 from/dur、SceneShell 的 from/durationInFrames 全部用帧。
- H3 片段 5s = 150 帧；beat 内 `durationInFrames` 与音频 wav 时长对齐。

## 转场
只兑现 {fade, cut}。用 `SceneShell`（见模板）：`fadeIn`/`fadeOut` 帧数即淡入淡出；cut 传 0。
slide/wipe/flip 在 Explainer 里未实现，别用。

## 常用矢量场景

### 大数字 StatCard（模板已含）
```tsx
<StatCard value="58.7" label="VO2max · 18岁运动员前1%" size={140} accent={GOLD} />
```
数字用等宽字体（FONT_MONO），加 textShadow 发光；入场用 spring 放大 + blur→0。

### 条形图（周运动结构等）
```tsx
const data = [
  { label: '力量', v: 3, color: ACCENT },    // 次
  { label: 'Zone 2', v: 150, color: '#10B981' }, // 分钟
  { label: 'HIIT', v: 75, color: GOLD },
];
// 每根条：宽度 interpolate(frame, [start+i*8, start+i*8+20], [0, v/max*W])
```
逐条错峰浮入（`start + i*8`），高度固定、宽度动画，数字 odometer 滚动可选。

### 时间轴（进食窗口/睡眠/翻车历史）
横向线 + 节点圆点；节点用 `interpolate` 沿 x 移动 + 到点弹入标签。
```tsx
const x = interpolate(frame, [0, DURATION], [pad, W-pad]);
```

### 对比表（完整方案 vs 25 岁版）
两列卡片，左列灰暗（$2M/111 药/极端断食），右列高亮（睡够/150min/SPF30/<$100/月）。
左列从左滑入、右列从右滑入，中间一个 "vs" 圆点。

### 补剂网格 supplement_grid
卡片网格，每卡：成分名（大字）+ 剂量（等宽）+ 证据强度点（●强/●中/○弱，颜色区分）。
逐卡 spring 浮入，`delay = i*5` 帧。

### 证据分级条 evidence_bars
横向条形，长度=证据强度，颜色：绿(强,肌酸)/蓝(缺乏时合理,Omega3·D3·镁)/灰(plausible 未证实,CaAKG·NR·锂)。

### 引言金句 QuoteCard
大引号 + 斜体衬线字 + 出处（Brenner/Barzilai）。背景 H3 压暗 0.7。

## H3 + 矢量叠加（标准模式）
```tsx
<AbsoluteFill>
  <H3Clip src="assets/video/h3_6.mp4" durationInFrames={480} dim={0.55} volume={0.15} />
  {/* 矢量层 */}
  <div style={{ position:'absolute', top:120, left:120 }}>
    <div style={{ color: INK, fontSize: 48 }}>2023 年轻血浆 → 叫停</div>
  </div>
</AbsoluteFill>
```
- H3 永远 full-bleed、cover、带运动（Ken Burns），上面叠暗层再叠矢量；
- 文字距画面边缘 ≥120px，避开左下 SpeakerBadges 和底部字幕；
- 关键信息落定后 hold ≥1s（让人读完）。

## 音频
- BGM：`volume={(f)=>BGM_ENVELOPE[f]}`，预计算 1f 分辨率数组；旁白段 duck 到 0.17。
- H3 原生音轨：旁白段 `volume={0.15}`，纯画面段可保留当环境床。
- SFX 钉帧：paper-slide（纸卡落定）、clock-tick（数字定格）、ui-notify（标注弹出）。
- 所有 Audio 包在 `<Sequence from={} durationInFrames={}>`。

## 字体与防豆腐块
- `@font-face` 从 `public/fonts/` 加载 NotoSansSC-VF.ttf / NotoSerifSC-VF.ttf（渲染机无 CJK 系统字体、无出网）。
- `FontGate` 首帧前 `document.fonts.load` 所有字重，失败不阻塞（fallback，但抽帧会发现豆腐块）。
- 混排拉丁数字+中文用 `FONT_MONO_CJK = '"DejaVu Sans Mono","Noto Sans SC",monospace'`。

## 确定性（硬规则）
- ❌ `Date.now()`、`Math.random()`、`new Date()`、`Math.random`
- ✅ 固定种子 `h(n) = fract(sin(n*127.3)*43758.5453)`
- 粒子/光斑位置用 `h(i)` 预生成数组，不随帧随机。

## 性能
- 180s 片约 5400 帧，`--concurrency=6 --gl=angle`，约 15–20 分钟。
- 避免每帧重算大数组（用 useMemo 或模块级常量）；BGM_ENVELOPE 模块级 IIFE 预计算。
- 字体加载用 delayRender/continueRender，别让首帧字体没到就渲染。

## 参考实现
- `deliverables/index.tsx`（64s 片，10 种场景：H3+stat、终端动画、里程表、纸卡、H3 金粒等）
- `blueprint/RESEARCH_AND_PRODUCTION_PLAN.md`（180s 片的完整分镜与数据设计）
