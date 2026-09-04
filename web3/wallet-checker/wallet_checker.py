from decimal import Decimal


def format_balance(balance_wei: int) -> str:
    """Convert Wei to ETH with readable formatting."""
    balance_eth = Decimal(balance_wei) / Decimal(10**18)
    return f"{balance_eth:.6f} ETH"


def main():
    print("=== Web3 Wallet Checker ===")

    wallet = input("Wallet address: ").strip()

    if not wallet:
        print("Error: wallet address is required.")
        return

    print(f"\nWallet: {wallet}")
    print("Status: address received")


if __name__ == "__main__":
    main()
