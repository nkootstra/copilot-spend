def test_module_imports():
    import copilot_spend
    import copilot_spend.cli

    assert callable(copilot_spend.cli.main)
