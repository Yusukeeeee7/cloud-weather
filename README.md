# cloud-weather

[日本語](#日本語) | [English](#english)

---

## 日本語

### なぜ作ったか

東京とベルリンの両方に住んでみて、**雲の高さがちがう**と感じました。

ヨーロッパの冬は「暗い」とよく言われます。それを聞いて、なぜだろうと考えたとき、
**雲が低くて、空が暗くなり、上から押さえつけられるような圧迫感があるから**ではないかと思いました。
東京でも雲が低い日はありますが、ヨーロッパほどの暗さや圧迫感を感じることはあまりありませんでした。

そこで、「今日は雲が近くて、圧迫感があるかもしれない」と前もってわかったら面白いのでは、と思い、
東京とベルリンの雲の高さを分析し、API と雲底高度の予測モデルを作ってみました。

### 緯度による違い

雲の高さは、緯度によっても違うようです。

- **低緯度（赤道付近）**：対流圏（雲ができる空気の層）の厚さが約 16 km あります。
  雲が縦に大きく育ちやすく（積乱雲など）、雲全体が高い空まで届きます。
- **高緯度（極付近）**：対流圏の厚さは約 8 km しかありません。
  雲ができる空間の「天井」が低いので、雲全体の高さも低緯度より低くなります。

ベルリン（北緯約 52 度）は、東京（北緯約 36 度）よりかなり北にあります。
ヨーロッパの冬に雲が低く感じるのは、この緯度の違いも関係しているのかもしれません。
ただし、対流圏の厚さが直接きくのは主に雲の「てっぺん」の高さで、
雲の「底」の高さは、空気の湿り具合（気温と露点の差）などにも左右されます。

### できること

- **雲底高度の予測**：東京（羽田空港 RJTT）とベルリン（ベルリン・ブランデンブルク空港 EDDB）の、雲の底の高さ（メートル）を予測します。
- **分析**：空港の観測データ（METAR）を使って、2 都市の雲の高さのちがいを調べました（`notebooks/`、`docs/eda.md`）。
- **天気 API**：Open-Meteo の天気予報から、必要な項目だけを整えて返します。
- **画面**：ブラウザで 2 都市を見くらべられる簡単なページがあります。

予測モデルの詳しい内容と結果は [`docs/model-card.md`](docs/model-card.md) にあります。
学習用のプロジェクトなので、航空の運航などの判断には使えません。

### 動かし方

```bash
uv sync
uv run uvicorn app.main:app --reload   # http://localhost:8000
# または
docker compose up --build              # API + Redis
```

### データの出典

- 天気：[Open-Meteo](https://open-meteo.com/)（CC BY 4.0）
- 空港の観測（METAR）：Iowa Environmental Mesonet, Iowa State University

---

## English

### Why I made this

I have lived in both Tokyo and Berlin, and I felt that **the clouds are at different heights** in the two cities.

People often say that winter in Europe is "dark". When I heard this, I wondered why.
My idea was this: **the clouds are low, so the sky gets dark, and you feel like something is pressing down on you.**
Tokyo also has days with low clouds, but I did not feel the same darkness or pressure there as in Europe.

So I thought it would be interesting to know in advance:
"Today the clouds may be close, and it may feel heavy outside."
To do this, I analyzed cloud heights in Tokyo and Berlin, and built an API and a model that predicts the cloud base height.

### Differences by latitude

Cloud heights also seem to change with latitude.

- **Low latitudes (near the equator)**: the troposphere (the layer of air where clouds form) is about 16 km thick.
  Clouds can grow tall (for example, thunderclouds), and the whole cloud can reach high into the sky.
- **High latitudes (near the poles)**: the troposphere is only about 8 km thick.
  The "ceiling" for clouds is lower, so clouds are generally lower than at low latitudes.

Berlin (about 52°N) is much further north than Tokyo (about 36°N).
This difference in latitude may be one reason why clouds feel low in European winters.
However, the thickness of the troposphere mainly affects the height of the cloud *top*.
The height of the cloud *base* also depends on other things, such as how humid the air is
(the gap between temperature and dew point).

### What it does

- **Cloud base prediction**: predicts the height of the cloud base (in meters) for Tokyo (Haneda Airport, RJTT) and Berlin (Berlin Brandenburg Airport, EDDB).
- **Analysis**: uses airport weather reports (METAR) to compare cloud heights in the two cities (`notebooks/`, `docs/eda.md`).
- **Weather API**: takes forecasts from Open-Meteo and returns only the fields that are needed.
- **Web page**: a simple page to compare the two cities in your browser.

You can find details and results of the model in [`docs/model-card.md`](docs/model-card.md) (in Japanese).
This is a learning project. Please do not use it for flight operations or other safety decisions.

### How to run

```bash
uv sync
uv run uvicorn app.main:app --reload   # http://localhost:8000
# or
docker compose up --build              # API + Redis
```

### Data sources

- Weather: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0)
- Airport observations (METAR): Iowa Environmental Mesonet, Iowa State University
