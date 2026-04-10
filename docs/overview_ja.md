# Overview

この文書では、uxaudit が何者で、どこに位置し、何を目指しているかを README より長い形で説明します。

## E2E が教えてくれることと、uxaudit が教えてくれること

| レイヤー | 問い | ツール |
|---|---|---|
| Unit | 「部品や関数は仕様通りに動くか？」 | Jest / Vitest / pytest |
| Property-based | 「不変条件は広い入力でも成り立つか？」 | fast-check / Hypothesis |
| Integration | 「組み合わせても壊れないか？」 | Jest / Vitest / pytest |
| E2E | 「フローは正しく実行できるか？」 | Playwright / Cypress |
| Visual / A11y checks | 「見た目の破綻や accessibility の重大な失敗はないか？」 | Percy / Chromatic / axe / Playwright |
| **⬆ ここまでは CI を green にできる ⬆** | | |
| **⬇ ここからは実際に使い物になるかの領域 ⬇** | | |
| **uxaudit** | **「人間や browser-use agent / computer-use agent が、理解し、次の行動を選び、コアの job を達成し、必要なら回復できるか？」** | **uxaudit** |
| Manual QA / dogfooding | 「何か感覚的におかしくないか？」 | humans |

accessibility と UI quality は、後段にだけ置く単独レイヤーではなく横断品質です。

- **CI 側** では semantic check、keyboard 操作、visual regression、responsive breakage、明白な interaction failure として現れる
- **uxaudit 側** では「理解できるか」「次の行動を選べるか」「詰まったときに回復できるか」という問いとして現れる

E2E が通ることは必要ですが、それだけで ship-ready とは言えません。プロダクトは次のような状態になり得ます。

- **使いにくい**: 主要ジャーニーが途切れる、空状態が弱い、コントラストが読みにくい
- **AI slop っぽい**: 汎用的な紫グラデーション、`your AI copilot` 的な文言、shadcn 既定感、絵文字アイコン、`coming soon`
- **アクセシブルでない**: WCAG AA 違反、キーボード到達不可、タップターゲット不足
- **一貫性がない**: デザインシステムの揺れ、タイポグラフィの崩れ、導線の受け渡し不全

browser-use agent や computer-use agent が QA や support、運用に入り始めると、同じ UX の欠陥が人間にも agent にも効いてきます。価値が伝わらない、ヒエラルキーが弱い、導線が死ぬ、無駄なステップが多い、回復の手がかりがない、といった問題です。

## 対象範囲

uxaudit は「website 専用」ではありませんが、「すべての app」を対象にしているわけでもありません。

ここでいう `app` には、web app、browser-based な product surface、task-oriented な website を含みます。

- **現在サポート:** web app / browser-like runtime
- **追加で対応:** Electron。ランタイムを同じ session 内で起動・キャプチャできる場合
- **エスカレーションで到達可能:** `computer-use` を使って一時的に OS 面へまたがる flow
- **対象外:** pure native の macOS / iOS / Android app、CLI

本質的な境界は `web か desktop か` ではなく、**capture できて agent が操作可能な rendered interface かどうか** です。`computer-use` は到達面を広げますが、それだけで native app が first-class target になるわけではありません。

## Product claim

uxaudit は、correctness checks と manual design review の間にある、抜け落ちていた品質レイヤーです。

- **E2E** は「フローが動くか」を教える
- **Visual / A11y checks** は「見た目や操作可能性の重大な破綻がないか」を教える
- **uxaudit** は「体験が理解可能で、使えて、意図的に設計されているか」を教える
- **最終判断は人間** がするが、曖昧な違和感ではなく、具体的なレポートから始められる

これは「AI が UI を採点する」ためのツールではありません。  
やりたいことは **アプリ向けの UX regression testing** です。

- 実アプリに対して走る
- visible artifacts と live journey を検査する
- core job が低い摩擦で first value に届くかを見る
- iteration を比較する
- 単発の感想ではなく、修正可能な feedback loop を作る

## Positioning

uxaudit は **アプリ向けの UX regression testing** として読むべきで、website grader でも、少し賢い lint でもありません。

- **UI polish だけを見るものではない**  
  人が product を理解できるか、次の行動を選べるか、first value に届くか、詰まったときに回復できるかを見る
- **correctness の代替ではない**  
  E2E が「動いたか」を見て、uxaudit が「その体験に意味が通っていたか」を見る
- **generic な事業戦略評価ではない**  
  何を作るべきかは決めない。いま作っている product が、その product 自身の job に対して readable / operable かを評価する

現時点でいちばん強い wedge は次です。

- **アプリ向けの UX regression testing**
- **Playwright / coding agent / vibe coding で速く作るチーム向け**
- **多くの場合 E2E の後、merge / release 前に回す品質ゲート**

## 何がいちばん重要か

uxaudit の本丸は checklist の数ではありません。重要なのは次の組み合わせです。

- **Journey evaluation**  
  このプロダクトの重要な仕事が、行き止まりや無駄な迷いなしに本当に完了できるか
- **Project-shaped evaluation**  
  このプロダクトにおける first value は何か、何を理解できるべきか、どの判断は obvious であるべきか、どこで recovery が重要か
- **Continuous feedback loop**  
  iteration 比較、別プロジェクト比較、改善の継続運用まで含めて UX 品質を追えるか

accessibility、AI slop、visual craft の check も重要です。これらは品質の床を強くし、レポートの信用を作ります。  
ただ、これらはあくまで支えるチェックであって、それだけだと「強い lint」で終わります。

uxaudit を別物にしているのは、**generic checks** から **project-aware journey auditing** へ進んでいること、その結果を history・compare・ranked proposals までつなげていることです。

別の言い方をすると:

- **UI risk checks** は品質の床を守る
- **UX regression checks** は product の本当の job が成立しているかを決める

## 何をするか / 何をしないか

### uxaudit の責務

- 実行中の interface をキャプチャする（DOM / CSS / screenshot）
- 5 カテゴリ・約 40 checks を実行する
- catalog check と journey check を判定する
- デザインシステム上正当な例外は Reconciler で吸収する
- root cause ごとに ranked fix plan を提案する
- 証拠、引用、履歴、比較、提案を含む self-contained HTML dashboard を出す

### uxaudit の責務ではないこと

- fix loop を自動で完了させること
- E2E の代わりになること
- performance benchmark になること
- correctness checker になること
- market fit を判定すること
- native app の監査基盤になること

## Current maturity

uxaudit はすでに product としての形を持っていますが、現時点では **alpha** として読むのが適切です。

- **すでに強い** — deterministic な catalog checks、capture pipeline、evidence model、dashboard、history / compare / library、project-context schema、ranked proposal model
- **伸びている最中** — project-shaped briefs、first-value framing、pixel-only journey judging、cross-check synthesis
- **まだ first-class ではない** — `decide` と `recover` の厚い評価、scenario coverage の拡張、Claude Code 外でも tighter に回る standalone orchestration

これは重要です。目標が UI lint ではなくアプリ向けの UX regression testing だからこそ、その中核の一部はまだ実装を強くしている途中です。

## なぜ今か

- **correctness testing だけでは足りない**  
  フローの正しさをかなり担保できても、UX regression、初回体験の詰まり、弱いジャーニーは普通に残る
- **Agent がループに入り始めている**  
  coding agent や browser-use agent、computer-use agent が開発、QA、support に入るので、UI は人間にも agent にも readable である必要がある
- **feedback loop を継続化できる**  
  uxaudit は iteration 保存、比較、cross-project library を持ち、コードが変わる環境の中でそのまま回せる

## Continuous workflow

これは単発レポートではありません。history / library view によって、`修正を選ぶ → 実装する → 再実行する → 比較する` を回せるようにしています。

<p align="center">
  <img src="../assets/en/dashboard-history.png" alt="uxaudit history dashboard" width="49%" />
  <img src="../assets/en/dashboard-library.png" alt="uxaudit library dashboard" width="49%" />
</p>

## Roadmap

Roadmap も generic な site audit に広げるのではなく、アプリ向けの UX regression testing を強くする方向で進むべきです。

### 1. いまの UX regression coverage を疑われにくくする

- L3 / L4 Judge dispatch を routine なフローとして固める
- sample app / sample output を用意し、first value や primary journey の finding を見せる
- pre-ship な UX regression run の PR / CI usage を導入しやすくする

### 2. `decide` と `recover` を first-class にする

- decision cost、defaulting、choice overload の brief を明示生成する
- undo、retry、backtracking、state preservation を first-class check にする
- iteration 比較で job friction を安定的に追えるようにする

### 3. project-shaped discovery を強くする

- multi-job app、journey chain、role-specific flow に強くなる
- regulated / high-trust domain の expectations を扱いやすくする
- 発見された journey が少なすぎるときに coverage weakness を強く可視化する

### 4. UX regression layer として標準化しやすくする

- CI-ready workflow と integration example を揃える
- external contributor 向けの contribution docs と check-authoring example を揃える
- Claude Code 以外での portability story を明確にする

## Check categories

以下は audit surface です。主役はこれ自体ではなく、それらを project-aware な journey evaluation に接続することです。すべての judgment-call check は公開された根拠に紐づきます。WCAG 2.2、NN/g、Nielsen、Krug、Baymard、ISO 9241 などを使い、`なんとなく` を避けます。

| Category | 見るもの | 例 |
|---|---|---|
| `ai-slop/` | AI 生成 UI の fingerprint | 紫グラデーション、shadcn 既定感、`coming soon`、絵文字アイコン |
| `accessibility/` | WCAG 2.2 AA の床 | axe-core、contrast、tap target、focus ring |
| `usability/` | Nielsen heuristics、journey continuity | error recovery、empty state、consistency、feedback |
| `core-experience/` | 主要ジャーニーの完遂 | signup、初回作成、share まで行けるか |
| `desirability/` | visual craft、copy、第一印象 | typography、voice、delight moment、aesthetic impression |

詳しい citation list は [../skills/uxaudit/references/knowledge/sources.md](../skills/uxaudit/references/knowledge/sources.md) を参照してください。
