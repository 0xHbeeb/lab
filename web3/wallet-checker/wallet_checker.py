from decimal import Decimal

from web3 import Web3


RPC_URL = "https://ethereum-rpc.publicnode.com"


def format_balance(balance_wei: int) -> str:
    """Convert Wei to ETH with readable formatting."""
    balance_eth = Decimal(balance_wei) / Decimal(10**18)
    return f"{balance_eth:.6f} ETH"


def main():
    print("=== Web3 Wallet Checker ===\n")

    wallet = input("Wallet address: ").strip()

    if not Web3.is_address(wallet):
        print("Error: invalid wallet address.")
        return

    w3 = Web3(Web3.HTTPProvider(RPC_URL))

    if not w3.is_connected():
        print("Error: could not connect to Ethereum RPC.")
        return

    wallet = Web3.to_checksum_address(wallet)

    balance_wei = w3.eth.get_balance(wallet)

    print("\nWallet Information")
    print("------------------")
    print(f"Address : {wallet}")
    print(f"Network : Ethereum")
    print(f"Balance : {format_balance(balance_wei)}")


if __name__ == "__main__":
    main()
