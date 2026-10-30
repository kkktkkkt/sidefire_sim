# テストについて

`sidefire_simulator.html`（単一HTMLファイルのSideFIREシミュレータ）に対する自動テストです。
Node.js/npmがこのマシンに無いため、既に導入済みのPython + Playwrightを使い、実ファイルを
headless Chromiumで読み込んで動かすことで、アプリの実際のコード（JS関数・DOM）をそのまま
検証します。ロジックを別言語に移植してテストする方式ではありません（税額計算のみ、後述の
理由でクロスチェック用に独立実装を用意しています）。

## 実行方法

```bash
cd F:/prog/SideFire_Sim
python tests/test_sidefire_simulator.py
```

- `playwright`パッケージとChromiumが必要です。未導入の場合（Pythonを入れ替えた後など）は
  `python -m pip install playwright` と `python -m playwright install chromium` を実行してください。
- Chart.jsをCDN（jsdelivr）から読み込むため、**ネットワーク接続が必須**です。オフラインだと
  最初の`[FAIL]`で「Chart.js CDN が読み込めない」旨のタイムアウトエラーになります。
- 出力は `[PASS] test_name` / `[FAIL] test_name - 失敗理由` が1テストずつ表示され、最後に
  `N passed, M failed` のサマリー行が出ます。1件でも失敗すると終了コードが1になります。

## 仕組み

- `sync_playwright()` で1つのブラウザを起動し、**テストごとに新しい `BrowserContext`**（＝新しい
  `localStorage`とDOM）を作ってから対象ファイルを`file://`で開きます。テスト間の状態汚染を防ぐためです。
- ロケールは `en-US` に固定しています。アプリ内の金額表示（`toLocaleString()`）の桁区切りが
  実行環境のロケールに依存してテスト結果がぶれるのを防ぐためです。
- 各テストの実行中に発生したJSの`console.error`や実行時例外（`pageerror`）は自動的に収集され、
  テスト本体のアサーションが通っても、エラーが1件でもあれば失敗として扱われます。想定外の
  JSエラーを取りこぼさないための仕組みです。
- `page.evaluate()` からアプリの `formatMan` / `calcAfterTaxIncome` / `getChildEduCostAtAge` /
  `getTotalEduCostForChild` / `getEduCostForYear` / `runMonteCarlo` などのトップレベル関数、および
  `children` グローバル変数を直接呼び出し・書き換えできます（HTML内の`<script>`がクラシックスクリプト
  のため、これらはページのグローバルスコープに存在し、Playwright側から直接アクセス可能です）。

## テスト一覧（19件）

| # | 関数・機能 | 内容 |
|---|---|---|
| 1 | `formatMan()` | 万円/億円のしきい値、マイナス値、`undefined`/`NaN`時のプレースホルダー表示（`― 万円`） |
| 2 | `calcAfterTaxIncome()` | 日本の給与所得税・住民税・社会保険料（社会保険料控除・住民税の基礎控除43万を含む）の概算式を独立にPython移植し、複数の年収（控除区分の境界値含む）でJS実装とクロスチェック。デフォルト年収700万円については画面表示（`#afterTaxDisplay`）とも突き合わせ |
| 3 | `getChildEduCostAtAge()` | 小中高大それぞれの年齢範囲での教育費、範囲外（0円になるべき年齢）の境界 |
| 4 | `getTotalEduCostForChild()` | 1人の子供の教育費合計を手計算値と照合 |
| 5 | `getEduCostForYear()` | `children`配列を直接注入し、年齢オフセットの解決を確認 |
| 6 | `runMonteCarlo()`（暴落確率0%） | 暴落が起きないので全試行が同一パスになり、p10=p50=p90になることを確認（決定的な性質のテスト） |
| 7 | `runMonteCarlo()`（暴落確率10%） | p10 ≤ p50 ≤ p90 の順序が全年で保たれること、資産枯渇率が0〜1の範囲内であること |
| 7a | `runMonteCarlo()`（回復ブースト） | `Math.random`を差し替えて初年度だけ暴落させ、回復期間（5年）後に暴落なしの推移と一致すること |
| 7b | `calcYearFlow()`（FIRE前の積立） | 手取り−生活費−教育費 が積立額に届かない年は積立が余剰分までに減り、赤字なら資産から取り崩す（税ONなら÷0.8）こと |
| 7c | インフレ率スライダー | 名目5%・インフレ1%で実質4.0%と表示され、インフレ率を上げると100歳時点の資産（現在価値）が減ること |
| 7d | 表示範囲スライダー | 現在41歳でも上限の100歳を選べること（min が5の倍数に揃っていること） |
| 7e | 暴落確率のヒント | 5%以下で「稀なケース」と表示されること |
| 8 | 初期表示 | localStorageが空の状態でページを開くと、子供カードが2件（10歳・4歳の順）作成されること |
| 9 | 子供の追加・削除（UI操作） | 「＋子供を追加」ボタンで+1件、削除ボタンで-1件。全員削除後は教育費カードが`formatMan(0)`表示になり、JSエラーが出ないこと |
| 10 | `simulate()`の入力連携 | 各種入力欄に値を入力すると、目標額カードとテーブル行数（`100 - 現在年齢 + 1`行）が正しく更新されること |
| 11 | 暴落シミュレーション トグル | ONにするとバナーに「資産枯渇リスク」表示、凡例（`#crashLegend`）が表示されること |
| 12 | 取り崩し税トグル | ONにすると4%ルール目標額がOFF時の1.25倍（税20%分）になること |
| 13 | localStorage永続化 | 入力値がリロード後も復元されること |
| 14 | 子供0人の永続化 | 子供を全員削除してリロードしても、初期値の子供2人が復活しないこと |

## 注意点（今後このテストを保守する人へ）

- このテストファイルはアプリ本体と型的に連動していません。`simulate()`・`runMonteCarlo()`の
  引数やDOMのid（`#card-target4`など）を変更した場合は、`tests/test_sidefire_simulator.py`も
  合わせて更新してください。
- `calcAfterTaxIncome()`のみ、テスト側に独立したPython実装（`reference_after_tax_income`）を
  用意しています。これは税額の累進計算式が正しく書き写されているかを検算する目的であり、
  他の関数のようにアプリの関数をそのまま呼び出す方式とは異なります。本体側の税率・控除額を
  変更した場合は、このPython版の数値もあわせて更新する必要があります。
