from decimal import Decimal

from web3 import Web3


ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


NETWORKS = {
    "1": {
        "name": "Ethereum",
        "rpc": "https://ethereum-rpc.publicnode.com",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        },
    },
    "2": {
        "name": "Arbitrum",
        "rpc": "https://arbitrum-one-rpc.publicnode.com",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            "USDT": "0xFd086bC7CD5C481Dcc9C85ebe478A1C0b69FCbb9",
        },
    },
    "3": {
        "name": "Base",
        "rpc": "https://base-rpc.publicnode.com",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        },
    },
    "4": {
        "name": "Optimism",
        "rpc": "https://optimism-rpc.publicnode.com",
        "native_symbol": "ETH",
        "tokens": {
            "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097F5F1",
            "USDT": "0x94b008Aa00579c1307B0EF2c499AD98a8ce58E58",
        },
    },
}


def format_amount(raw_balance: int, decimals: int) -> str:
    amount = Decimal(raw_balance) / Decimal(10**decimals)
    return f"{amount:.6f}"


def choose_network():
    print("Select network:\n")

    for key, network in NETWORKS.items():
        print(f"{key}. {network['name']}")

    while True:
        choice = input("\nNetwork: ").strip()

        if choice in NETWORKS:
            return NETWORKS[choice]

        print("Invalid selection. Choose a number from the list.")


def get_native_balance(w3: Web3, wallet: str, symbol: str) -> str:
    balance_wei = w3.eth.get_balance(wallet)
    balance = Decimal(balance_wei) / Decimal(10**18)

    return f"{balance:.6f} {symbol}"


def get_token_balance(
    w3: Web3,
    wallet: str,
    token_address: str,
) -> tuple[str, str]:
    token = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )

    symbol = token.functions.symbol().call()
    decimals = token.functions.decimals().call()
    raw_balance = token.functions.balanceOf(wallet).call()

    return symbol, format_amount(raw_balance, decimals)


def check_wallet(network: dict, wallet: str):
    w3 = Web3(Web3.HTTPProvider(network["rpc"]))

    if not w3.is_connected():
        print("Error: could not connect to RPC.")
        return

    wallet = Web3.to_checksum_address(wallet)

    print("\nWallet Information")
    print("------------------")
    print(f"Address : {wallet}")
    print(f"Network : {network['name']}")
    print(
        f"Balance : "
        f"{get_native_balance(w3, wallet, network['native_symbol'])}"
    )

    print("\nToken Balances")
    print("--------------")

    for token_name, token_address in network["tokens"].items():
        try:
            symbol, balance = get_token_balance(
                w3,
                wallet,
                token_address,
            )

            print(f"{symbol:<8}: {balance}")

        except Exception as error:
            print(f"{token_name:<8}: unavailable")


def main():
    print("=== Web3 Wallet Checker v3 ===\n")

    network = choose_network()

    wallet = input("\nWallet address: ").strip()

    if not Web3.is_address(wallet):
        print("Error: invalid wallet address.")
        return

    check_wallet(network, wallet)


if __name__ == "__main__":
    main()