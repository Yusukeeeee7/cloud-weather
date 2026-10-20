"""ブランチ保護の確認用（#53）。この PR はマージせずに閉じる。"""


def test_fails_on_purpose() -> None:
    assert 1 == 2
