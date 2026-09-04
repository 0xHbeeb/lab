from decimal import Decimal

from web3 import Web3


NETWORKS = {
    "1": {
        "name": "Ethereum",
        "rpc": "https://ethereum-rpc.publicnode.com",
        "symbol": "ETH",
    },
    "2": {
        "name": "Arbitrum",
        "rpc": "https://arbitrum-one-rpc.publicnode.com",
        "symbol": "ETH",
    },
    "3": {
        "name": "Base",
        "rpc": "https://base-rpc.publicnode.com",
        "symbol": "ETH",
    },
    "4": {
        "name": "Optimism",
        "rpc": "https://optimism-rpc.publicnode.com",
        "symbol": "ETH",
    },
}


def format_balance(balance_wei: int, symbol: str) -> str:
    """Convert Wei to a readable native token balance."""
    balance = Decimal(balance_wei) / Decimal(10**18)
    return f"{balance:.6f} {symbol}"


def choose_network():
    print("Select network:\n")

    for key, network in NETWORKS.items():
        print(f"{key}. {network['name']}")

    while True:
        choice = input("\nNetwork: ").strip()

        if choice in NETWORKS:
            return NETWORKS[choice]

        print("Invalid selection. Choose a number from the list.")


def check_wallet(network: dict, wallet: str):
    w3 = Web3(Web3.HTTPProvider(network["rpc"]))

    if not w3.is_connected():
        print("Error: could not connect to RPC.")
        return

    wallet = Web3.to_checksum_address(wallet)
    balance_wei = w3.eth.get_balance(wallet)

    print("\nWallet Information")
    print("------------------")
    print(f"Address : {wallet}")
    print(f"Network : {network['name']}")
    print(f"Balance : {format_balance(balance_wei, network['symbol'])}")


def main():
    print("=== Web3 Wallet Checker v2 ===\n")

    network = choose_network()

    wallet = input("\nWallet address: ").strip()

    if not Web3.is_address(wallet):
        print("Error: invalid wallet address.")
        return

    check_wallet(network, wallet)


if __name__ == "__main__":
    main()