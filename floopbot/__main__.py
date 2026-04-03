"""
Floopbot replay tester - CLI entry point.

Usage:
    python -m floopbot                          # Run with defaults
    python -m floopbot --dashboard              # Launch web dashboard
    python -m floopbot --symbol MNQ1! --tf 5    # Override symbol/timeframe
    python -m floopbot --config path/to/config  # Use custom config
    python -m floopbot --bars 500 --step        # Step mode, 500 bars
    python -m floopbot --save-config            # Save default config
    python -m floopbot --check                  # Connection check only
"""

import argparse
import json
import sys

from .config import TradingConfig
from .mcp_bridge import TVBridge
from .replay_runner import ReplayRunner, run_replay_test


def main():
    parser = argparse.ArgumentParser(
        description="Floopbot - Automated replay paper trading via TradingView MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m floopbot                              Run replay with defaults
  python -m floopbot --symbol MNQ1! --tf 5        Override symbol/timeframe
  python -m floopbot --bars 1000 --step           Step mode, 1000 bars
  python -m floopbot --date 2026-01-15            Start replay from date
  python -m floopbot --strength 10                Min signal strength 10/14
  python -m floopbot --atr-mult 2.0               ATR stop multiplier 2.0x
  python -m floopbot --check                      Test connection only
  python -m floopbot --save-config                Save default config file
        """,
    )

    parser.add_argument("--config", "-c", help="Path to config JSON file")
    parser.add_argument("--save-config", action="store_true", help="Save default config and exit")
    parser.add_argument("--check", action="store_true", help="Check connection and exit")
    parser.add_argument("--dashboard", action="store_true", help="Launch web dashboard UI")
    parser.add_argument("--port", type=int, default=8082, help="Dashboard port (default: 8082)")

    # Trading params
    parser.add_argument("--symbol", "-s", help="Symbol (e.g., MNQ1!, ES1!, NQ1!)")
    parser.add_argument("--tf", "--timeframe", help="Timeframe (e.g., 1, 5, 15, 60, D)")
    parser.add_argument("--contracts", type=int, help="Number of contracts")
    parser.add_argument("--strength", type=int, help="Min signal strength (1-14)")
    parser.add_argument("--atr-mult", type=float, help="ATR stop multiplier")
    parser.add_argument("--trail-atr", type=float, help="Trail distance in ATR")
    parser.add_argument("--max-loss", type=float, help="Max daily loss in dollars")

    # Replay params
    parser.add_argument("--date", "-d", help="Replay start date (YYYY-MM-DD)")
    parser.add_argument("--bars", "-b", type=int, help="Max bars to process (0=unlimited)")
    parser.add_argument("--step", action="store_true", help="Use step mode (slower, precise)")
    parser.add_argument("--speed", type=int, help="Autoplay speed in ms (0=fastest)")

    # Output
    parser.add_argument("--output", "-o", help="Output directory for results")
    parser.add_argument("--no-screenshots", action="store_true", help="Disable trade screenshots")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")

    args = parser.parse_args()

    # Load or create config
    config = TradingConfig.load(args.config) if args.config else TradingConfig()

    # Apply overrides
    if args.symbol:
        config.symbol = args.symbol
    if args.tf:
        config.timeframe = args.tf
    if args.contracts is not None:
        config.contracts = args.contracts
    if args.strength is not None:
        config.min_signal_strength = args.strength
    if args.atr_mult is not None:
        config.atr_stop_multiplier = args.atr_mult
    if args.trail_atr is not None:
        config.trail_distance_atr = args.trail_atr
    if args.max_loss is not None:
        config.max_daily_loss = args.max_loss
    if args.date:
        config.replay_start_date = args.date
    if args.bars is not None:
        config.bars_to_run = args.bars
    if args.step:
        config.step_mode = True
    if args.speed is not None:
        config.replay_speed_ms = args.speed
    if args.output:
        config.output_dir = args.output
    if args.no_screenshots:
        config.screenshot_on_trade = False
    if args.quiet:
        config.log_signals = False

    # Save config mode
    if args.save_config:
        path = args.config or "floop_config.json"
        config.save(path)
        print(f"Config saved to {path}")
        return

    # Connection check mode
    if args.check:
        bridge = TVBridge(
            cli_path=config.mcp_cli_path,
            cdp_host=config.cdp_host,
            cdp_port=config.cdp_port,
        )
        print("Checking CDP connection...")
        if bridge.cdp_available():
            print("CDP port 9222: CONNECTED")
            target = bridge.find_chart_target()
            if target:
                print(f"Chart target: {target.get('title', 'N/A')}")
                print(f"URL: {target.get('url', 'N/A')}")
            else:
                print("No TradingView chart target found")
        else:
            print("CDP port 9222: NOT AVAILABLE")
            print("Is TradingView running with --remote-debugging-port=9222?")

        print(f"\nMCP CLI: {config.mcp_cli_path or 'NOT FOUND'}")
        if config.mcp_cli_path:
            health = bridge.health_check()
            if health.success:
                print(f"MCP health: OK")
                print(json.dumps(health.data, indent=2))
            else:
                print(f"MCP health: FAILED - {health.error}")
        return

    # Dashboard mode
    if args.dashboard:
        from .dashboard import run_dashboard
        run_dashboard(config, port=args.port)
        return

    # Print config summary
    print("=" * 50)
    print("FLOOPBOT REPLAY TESTER")
    print("=" * 50)
    print(f"Symbol:     {config.symbol}")
    print(f"Timeframe:  {config.timeframe}")
    print(f"Mode:       {'Step' if config.step_mode else 'Autoplay'}")
    print(f"Bars:       {config.bars_to_run or 'unlimited'}")
    print(f"ATR Stop:   {config.atr_stop_multiplier}x")
    print(f"Trail:      {config.trail_distance_atr}x ATR ({config.trail_mode})")
    print(f"Min Str:    {config.min_signal_strength}/{config.max_signal_strength}")
    print(f"Max Loss:   ${config.max_daily_loss}")
    print(f"Output:     {config.output_dir}")
    print("=" * 50)
    print()

    # Run the replay test
    runner = ReplayRunner(config)

    if not runner.setup():
        print("\nSetup failed. Make sure:")
        print("  1. TradingView Desktop is running")
        print("  2. Launched with --remote-debugging-port=9222")
        print("  3. A chart is open with FLOOP Pro indicator")
        sys.exit(1)

    if not runner.start_replay():
        print("\nFailed to start replay. Check the chart state.")
        sys.exit(1)

    try:
        runner.run()
    except KeyboardInterrupt:
        print("\nInterrupted. Generating report...")
    finally:
        runner.stop()

    # Exit with appropriate code
    stats = runner.trader.stats
    if stats["total_trades"] == 0:
        print("\nNo trades were executed. Check your indicator and signal settings.")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
