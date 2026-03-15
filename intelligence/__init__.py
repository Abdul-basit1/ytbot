"""
UpperCut — Intelligence Engine (Phase 2)
Self-learning system that collects YouTube analytics, analyzes patterns,
and optimizes the pipeline strategy for each channel.

Usage:
    from intelligence import run_intelligence
    run_intelligence(channel_id=1)
"""

from __future__ import annotations

from typing import Dict, Optional

from loguru import logger

from intelligence.analytics_collector import collect_all
from intelligence.performance_analyzer import PerformanceReport, analyze
from intelligence.strategy_optimizer import get_strategy, optimize


def run_intelligence(channel_id: int, days_back: int = 28) -> Optional[Dict]:
    """
    Execute the full intelligence cycle for a channel:
    1. Collect — fetch latest YouTube analytics for all uploaded videos
    2. Analyze — find patterns in performance data
    3. Optimize — update the strategy table with learned recommendations

    This should be called after every pipeline run (or on a daily schedule)
    so the system continuously learns and improves.

    Args:
        channel_id: internal channel ID
        days_back: how many days of analytics to consider

    Returns:
        The updated strategy dict, or None if insufficient data.
    """
    logger.info(f"{'─'*50}")
    logger.info(f"INTELLIGENCE ENGINE — Channel {channel_id}")
    logger.info(f"{'─'*50}")

    # ── Step 1: Collect analytics ───────────────────────────────────────
    logger.info("Intelligence Step 1/3: Collecting YouTube analytics...")
    try:
        updated_count = collect_all(channel_id, days_back)
        logger.info(f"Collected analytics for {updated_count} videos")
    except Exception as e:
        logger.error(f"Analytics collection failed: {e}")
        # Non-fatal — we can still analyze previously collected data
        updated_count = 0

    # ── Step 2: Analyze performance ─────────────────────────────────────
    logger.info("Intelligence Step 2/3: Analyzing performance patterns...")
    try:
        report = analyze(channel_id)
    except Exception as e:
        logger.error(f"Performance analysis failed: {e}")
        report = None

    if not report:
        logger.info("Not enough data for analysis — intelligence engine will improve with more uploads")
        return get_strategy(channel_id)  # Return existing strategy if any

    # ── Step 3: Optimize strategy ───────────────────────────────────────
    logger.info("Intelligence Step 3/3: Optimizing strategy...")
    try:
        strategy = optimize(report)
    except Exception as e:
        logger.error(f"Strategy optimization failed: {e}")
        strategy = {}

    # Log recommendations
    if report.recommendations:
        logger.info("Intelligence Recommendations:")
        for rec in report.recommendations:
            logger.info(f"  → {rec}")

    logger.info(f"{'─'*50}")
    logger.info(f"INTELLIGENCE ENGINE COMPLETE")
    logger.info(f"{'─'*50}")

    return strategy
