
import subprocess
import sys
import os

def run_test(name, command):
    print(f"\n>>> Running {name}...")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[SUCCESS] {name}")
            return True, result.stdout
        else:
            print(f"[FAILED] {name}")
            print(result.stderr)
            return False, result.stderr
    except Exception as e:
        print(f"[ERROR] {name}: {e}")
        return False, str(e)

def main():
    print("========================================")
    print("   TRADING BOT COMPREHENSIVE TEST RUNNER   ")
    print("========================================")
    
    tests = [
        ("Config Verification", f'"{sys.executable}" verify_config.py'),
        ("Technical Indicators", f'"{sys.executable}" -m pytest tests/test_indicators.py'),
        ("Synthetic Indicators", f'"{sys.executable}" -m pytest tests/test_indicators_synthetic.py'),
        ("Regime Transitions", f'"{sys.executable}" -m pytest tests/test_regime_transition.py'),
        ("Risk Management", f'"{sys.executable}" -m pytest tests/test_risk_manager.py'),
        ("Strategy Routing", f'"{sys.executable}" -m pytest tests/test_strategies.py'),
    ]
    
    results = []
    for name, cmd in tests:
        success, output = run_test(name, cmd)
        results.append((name, success))
        
    print("\n" + "="*40)
    print("            FINAL SUMMARY            ")
    print("="*40)
    
    failed = False
    for name, success in results:
        status = "PASSED" if success else "FAILED"
        print(f"{name:.<30} {status}")
        if not success:
            failed = True
            
    if failed:
        print("\n[!] SOME TESTS FAILED. CHECK LOGS ABOVE.")
        sys.exit(1)
    else:
        print("\n[+] ALL SYSTEMS GREEN. READY FOR DEPLOYMENT.")
        sys.exit(0)

if __name__ == "__main__":
    main()
