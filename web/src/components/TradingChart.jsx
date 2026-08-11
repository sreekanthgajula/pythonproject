import React, { useEffect, useRef } from 'react';
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts';

export default function TradingChart({ data }) {
  const chartContainerRef = useRef();
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const obvSeriesRef = useRef(null);
  const tsiSeriesRef = useRef(null);
  const tsiSignalSeriesRef = useRef(null);
  const seriesMarkersRef = useRef(null);

  // Initialize the chart once on mount
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight || 600,
      layout: {
        background: { type: 'solid', color: '#ffffff' },
        textColor: '#131722',
      },
      grid: {
        vertLines: { color: '#f0f3fa' },
        horzLines: { color: '#f0f3fa' },
      },
      timeScale: {
        borderColor: '#e0e3eb',
        timeVisible: true,
      },
    });

    // 1. Candlestick Series (Main Pane - Takes up top 50%)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#089981',
      downColor: '#f23645',
      borderVisible: false,
      wickUpColor: '#089981',
      wickDownColor: '#f23645',
      priceScaleId: 'right',
    });
    
    // Set auto scale for main price
    chart.priceScale('right').applyOptions({
      scaleMargins: {
        top: 0.05,
        bottom: 0.45,
      },
    });

    // 1.5. Volume Series (Overlaid at bottom of Main Pane)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#089981',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
      scaleMargins: {
        top: 0.42,
        bottom: 0.45,
      },
    });

    // 2. OBV Series (Sub-pane 1)
    const obvSeries = chart.addSeries(LineSeries, {
      color: '#7B1FA2',
      lineWidth: 2,
      priceScaleId: 'obv',
      title: 'OBV',
    });
    
    chart.priceScale('obv').applyOptions({
      scaleMargins: {
        top: 0.6,
        bottom: 0.25,
      },
    });

    // 3. TSI Series (Sub-pane 2)
    const tsiSeries = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 2,
      priceScaleId: 'tsi',
      title: 'TSI',
    });
    
    const tsiSignalSeries = chart.addSeries(LineSeries, {
      color: '#FF6D00',
      lineWidth: 1,
      priceScaleId: 'tsi',
      title: 'TSI Signal',
    });

    chart.priceScale('tsi').applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0.02,
      },
    });

    // Store references to chart and series
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    obvSeriesRef.current = obvSeries;
    tsiSeriesRef.current = tsiSeries;
    tsiSignalSeriesRef.current = tsiSignalSeries;

    const handleResize = () => {
      chart.applyOptions({
        width: chartContainerRef.current.clientWidth,
        height: chartContainerRef.current.clientHeight
      });
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesMarkersRef.current = null;
    };
  }, []);

  // Update chart series data when 'data' changes
  useEffect(() => {
    if (!data || data.length === 0) return;
    if (
      !candleSeriesRef.current ||
      !volumeSeriesRef.current ||
      !obvSeriesRef.current ||
      !tsiSeriesRef.current ||
      !tsiSignalSeriesRef.current
    ) return;

    candleSeriesRef.current.setData(data.map(d => ({
      time: d.time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    })));

    volumeSeriesRef.current.setData(data.map(d => ({
      time: d.time,
      value: d.volume,
      color: d.close >= d.open ? 'rgba(8, 153, 129, 0.35)' : 'rgba(242, 54, 69, 0.35)',
    })));

    obvSeriesRef.current.setData(data.map(d => ({
      time: d.time,
      value: d.obv,
    })));

    tsiSeriesRef.current.setData(data.map(d => ({
      time: d.time,
      value: d.tsi,
    })));

    tsiSignalSeriesRef.current.setData(data.map(d => ({
      time: d.time,
      value: d.tsi_signal,
    })));

    // Set markers for breakouts on the candlestick series
    if (candleSeriesRef.current) {
      const markers = data
        .filter(d => d.is_breakout)
        .map(d => ({
          time: d.time,
          position: 'belowBar',
          color: '#10b981', // Emerald green
          shape: 'arrowUp',
        }));

      if (!seriesMarkersRef.current) {
        seriesMarkersRef.current = createSeriesMarkers(candleSeriesRef.current, markers);
      } else {
        seriesMarkersRef.current.setMarkers(markers);
      }
    }

    // Fit content on initial load, but preserve user zoom on subsequent updates
    if (chartRef.current && data.length > 0) {
      // Just to ensure chart draws first frame correctly
      chartRef.current.timeScale().fitContent();
    }
  }, [data]);

  return <div ref={chartContainerRef} style={{ width: '100%', height: 'calc(100vh - 280px)', minHeight: '500px', marginTop: '20px', borderRadius: '12px', overflow: 'hidden', boxShadow: '0 4px 6px rgba(0,0,0,0.3)' }} />;
}
