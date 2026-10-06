import pandas as pd
from datetime import datetime


def collect():

    rows = []

    #
    # 這裡是 source adapter。
    #
    # 不要在這裡加入：
    #
    # - 登入 Cookie
    # - CAPTCHA bypass
    # - 私有 token
    # - 高頻 requests
    #
    # 後續我們把公開取得的 listing
    # 全部轉成下面統一格式。
    #

    return pd.DataFrame(
        rows,
        columns=[
            "listing_id",
            "name",
            "district",
            "address",
            "price",
            "area",
            "age",
            "rooms",
            "parking",
            "floor",
            "source",
            "url",
            "lat",
            "lon",
            "work1_distance",
            "work2_distance",
            "collected_at"
        ]
    )
