# Web3 Wallet Checker

A small Python tool for checking basic Ethereum wallet information.

## Features

→ Validate Ethereum wallet addresses  
→ Connect to an Ethereum RPC  
→ Check native ETH balance  
→ Convert Wei into readable ETH  

## Requirements

- Python 3.10+
- Web3.py

## Installation

Clone the repository:

```bash
git clone https://github.com/0xHbeeb/lab.git
cd lab/web3/wallet-checker
```
```bash
pip install -r requirements.txt
```
```bash
python wallet_checker.py
```

## Example
=== Web3 Wallet Checker ===

Wallet address: 0x...

Wallet Information
------------------
Address : 0x...
Network : Ethereum
Balance : 0.123456 ETH

## How it works
Wallet Address
      ↓
Validate Address
      ↓
Ethereum RPC
      ↓
Get ETH Balance
      ↓
Format Balance
      ↓
Display Result

## Status
🟡 Early experiment

This project is part of my personal lab for exploring Web3, Python, and on-chain systems.

More features may come as the experiment evolves.

Part of [0xHbeeb/lab.](https://github.com/0xHbeeb/lab)
