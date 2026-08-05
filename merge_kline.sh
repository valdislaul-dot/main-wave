#!/bin/bash
# 合并K线分片 → 解压
cat kline_data.tar.gz.part* > kline_data.tar.gz
tar xzf kline_data.tar.gz
echo "K线数据已解压到 data/kline_data/"
