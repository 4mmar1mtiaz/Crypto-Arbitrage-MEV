import json
import os
import asyncio
from web3 import Web3
from eth_account import Account
import time
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("arbitrage_bot.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("FlashloanArbitrageBot")

# Load environment variables
load_dotenv()
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_API_KEY = os.getenv("RPC_API_KEY")

# Runtime configuration - Define all globals at module level
SCAN_INTERVAL = 60  # seconds between scans
MIN_PROFIT_PERCENT = 0.15  # minimum profit percentage to execute trade
AUTO_EXECUTE = False  # set to True to automatically execute trades without confirmation
MAX_GAS_PRICE = 80  # maximum gas price in gwei to allow trading
FLASH_LOAN_AMOUNT = 5  # ETH - Default flash loan amount

# Initialize Web3 - MAINNET
w3 = Web3(Web3.HTTPProvider(f"https://eth-mainnet.g.alchemy.com/v2/{RPC_API_KEY}"))
account = Account.from_key(PRIVATE_KEY)

# IMPORTANT: Update with your actual deployed contract address
ARBITRAGER_ADDRESS = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
ROUTER1_ADDRESS = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
ROUTER2_ADDRESS = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")

# Top tokens by market cap/liquidity
WETH = Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")  # Wrapped Ether (borrowing token)
TOKEN1 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN2 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN3 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN4 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN5 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN6 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN7 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN8 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
TOKEN9 = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")

# Hard-coded ABIs for essential contracts
ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Correct ABI for executeArbitrage function
ARBITRAGE_EXECUTOR_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "borrowedToken", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address[]", "name": "path1", "type": "address[]"},
            {"internalType": "address[]", "name": "path2", "type": "address[]"}
        ],
        "name": "executeArbitrage",
        "outputs": [],
        "stateMutability": "nonpayable", 
        "type": "function"
    }
]

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Initialize contracts with hardcoded ABIs to avoid file loading issues
try:
    arbitrager_contract = w3.eth.contract(address=ARBITRAGER_ADDRESS, abi=ARBITRAGE_EXECUTOR_ABI)
    router1 = w3.eth.contract(address=ROUTER1_ADDRESS, abi=ROUTER_ABI)
    router2 = w3.eth.contract(address=ROUTER2_ADDRESS, abi=ROUTER_ABI)
    weth_contract = w3.eth.contract(address=WETH, abi=ERC20_ABI)
    
    logger.info("Contract interfaces initialized successfully")
except Exception as e:
    logger.error(f"Error initializing contracts: {str(e)}")

async def check_arbitrage_opportunity(token_address, amount_in):
    """Check for arbitrage opportunities between Router1 and Router2"""
    try:
        # Create paths
        path1 = [WETH, token_address]
        path2 = [token_address, WETH]
        
        # Get expected outputs
        try:
            router1_output1 = router1.functions.getAmountsOut(amount_in, path1).call()[1]
            router2_output1 = router2.functions.getAmountsOut(amount_in, path1).call()[1]
        except Exception as e:
            logger.error(f"Error getting price quotes: {str(e)}")
            return None
        
        # Check Router1 -> Router2
        if router1_output1 > 0:
            try:
                router2_output2 = router2.functions.getAmountsOut(router1_output1, path2).call()[1]
                
                if router2_output2 > amount_in:
                    # Calculate profit after flash loan fee (0.09%)
                    flash_loan_fee = int(amount_in * 0.0009)
                    profit = router2_output2 - amount_in - flash_loan_fee
                    profit_percent = (profit / amount_in) * 100
                    
                    if profit > 0:
                        logger.info(f"Router1 -> Router2 opportunity:")
                        logger.info(f"  Input: {w3.from_wei(amount_in, 'ether')} WETH")
                        logger.info(f"  Output: {w3.from_wei(router2_output2, 'ether')} WETH")
                        logger.info(f"  Flash Loan Fee: {w3.from_wei(flash_loan_fee, 'ether')} WETH")
                        logger.info(f"  Net Profit: {w3.from_wei(profit, 'ether')} WETH ({profit_percent:.2f}%)")
                        
                        return {
                            "route": "Router1 -> Router2",
                            "direction": 0,  # Direction.ROUTER1_ROUTER2
                            "token": token_address,
                            "profit_wei": profit,
                            "profit_eth": w3.from_wei(profit, 'ether'),
                            "profit_percent": profit_percent,
                            "input_amount": amount_in,
                            "token_amount": router1_output1,
                            "output_amount": router2_output2,
                            "min_token_amount": int(router1_output1 * 0.95),  # 5% slippage
                            "min_output_amount": int(amount_in * 1.001),  # Ensure profit + fees
                            "path1": path1,  # Include path arrays for executeArbitrage
                            "path2": path2
                        }
            except Exception as e:
                logger.error(f"Error checking Router1 -> Router2 route: {str(e)}")
        
        # Check Router2 -> Router1
        if router2_output1 > 0:
            try:
                router1_output2 = router1.functions.getAmountsOut(router2_output1, path2).call()[1]
                
                if router1_output2 > amount_in:
                    # Calculate profit after flash loan fee (0.09%)
                    flash_loan_fee = int(amount_in * 0.0009)
                    profit = router1_output2 - amount_in - flash_loan_fee
                    profit_percent = (profit / amount_in) * 100
                    
                    if profit > 0:
                        logger.info(f"Router2 -> Router1 opportunity:")
                        logger.info(f"  Input: {w3.from_wei(amount_in, 'ether')} WETH")
                        logger.info(f"  Output: {w3.from_wei(router1_output2, 'ether')} WETH")
                        logger.info(f"  Flash Loan Fee: {w3.from_wei(flash_loan_fee, 'ether')} WETH")
                        logger.info(f"  Net Profit: {w3.from_wei(profit, 'ether')} WETH ({profit_percent:.2f}%)")
                        
                        # Swap the path order for Router2 -> Router1 direction
                        return {
                            "route": "Router2 -> Router1",
                            "direction": 1,  # Direction.ROUTER2_ROUTER1
                            "token": token_address,
                            "profit_wei": profit,
                            "profit_eth": w3.from_wei(profit, 'ether'),
                            "profit_percent": profit_percent,
                            "input_amount": amount_in,
                            "token_amount": router2_output1,
                            "output_amount": router1_output2,
                            "min_token_amount": int(router2_output1 * 0.95),  # 5% slippage
                            "min_output_amount": int(amount_in * 1.001),  # Ensure profit + fees
                            "path1": path1,  # Include path arrays for executeArbitrage
                            "path2": path2
                        }
            except Exception as e:
                logger.error(f"Error checking Router2 -> Router1 route: {str(e)}")
        
        return None
        
    except Exception as e:
        logger.error(f"Error checking arbitrage: {str(e)}")
        return None

async def execute_flash_loan_arbitrage(opportunity):
    """Execute arbitrage using flash loan"""
    try:
        logger.info(f"Executing flash loan arbitrage: {opportunity['route']}")
        
        logger.info(f"Executing arbitrage with token: {opportunity['token']}")
        
        # Get current gas price and calculate appropriate gas settings
        gas_price = w3.eth.gas_price
        max_fee = gas_price * 2
        priority_fee = w3.to_wei(2, 'gwei')
        
        # Build the transaction
        nonce = w3.eth.get_transaction_count(account.address)
        
        # Use the executeArbitrage function with the path arrays
        arbitrage_tx = arbitrager_contract.functions.executeArbitrage(
            WETH,  # Borrow WETH
            opportunity['input_amount'],
            opportunity['path1'],
            opportunity['path2']
        ).build_transaction({
            'from': account.address,
            'gas': 700000,  # Increased gas limit for safety
            'maxFeePerGas': max_fee,
            'maxPriorityFeePerGas': priority_fee,
            'nonce': nonce,
        })
        
        # Sign and send transaction
        signed_tx = w3.eth.account.sign_transaction(arbitrage_tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        logger.info(f"Flash loan arbitrage transaction sent: {tx_hash.hex()}")
        
        # Wait for confirmation
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt['status'] == 1:
            logger.info(f"Flash loan arbitrage executed successfully! Gas used: {receipt['gasUsed']}")
            return True
        else:
            logger.error("Flash loan arbitrage transaction failed!")
            return False
        
    except Exception as e:
        logger.error(f"Error executing flash loan arbitrage: {str(e)}")
        return False

async def scan_continuously():
    """Continuously scan for arbitrage opportunities"""
    global FLASH_LOAN_AMOUNT, MIN_PROFIT_PERCENT, AUTO_EXECUTE
    
    # Convert flash loan amount to wei
    amount = w3.to_wei(FLASH_LOAN_AMOUNT, 'ether')
    
    # Tokens to check
    tokens = [TOKEN1, TOKEN2, TOKEN3, TOKEN4, TOKEN5, TOKEN6, TOKEN7, TOKEN8, TOKEN9]
    token_names = {
        TOKEN1: "TOKEN1",
        TOKEN2: "TOKEN2", 
        TOKEN3: "TOKEN3",
        TOKEN4: "TOKEN4",
        TOKEN5: "TOKEN5",
        TOKEN6: "TOKEN6",
        TOKEN7: "TOKEN7",
        TOKEN8: "TOKEN8",
        TOKEN9: "TOKEN9"
    }
    
    execution_count = 0
    scan_count = 0
    
    logger.info(f"Starting flash loan arbitrage scan (interval: {SCAN_INTERVAL} seconds)")
    logger.info(f"Flash loan amount: {FLASH_LOAN_AMOUNT} ETH")
    logger.info(f"Minimum profit threshold: {MIN_PROFIT_PERCENT}%")
    logger.info(f"Maximum gas price: {MAX_GAS_PRICE} gwei")
    logger.info(f"Auto-execute mode: {'ON' if AUTO_EXECUTE else 'OFF'}")
    
    try:
        while True:
            scan_count += 1
            logger.info(f"Scan #{scan_count} - Checking for arbitrage opportunities...")
            
            # Get current gas price
            gas_price = w3.eth.gas_price
            gas_price_gwei = w3.from_wei(gas_price, 'gwei')
            logger.info(f"Current gas price: {gas_price_gwei:.2f} gwei")
            
            # Skip if gas price is too high
            if gas_price_gwei > MAX_GAS_PRICE:
                logger.info(f"Gas price too high ({gas_price_gwei:.2f} gwei). Skipping this scan.")
                await asyncio.sleep(SCAN_INTERVAL)
                continue
            
            best_opportunity = None
            
            for token in tokens:
                token_name = token_names.get(token, token)
                logger.info(f"Checking {token_name} for arbitrage opportunities...")
                
                opportunity = await check_arbitrage_opportunity(token, amount)
                
                if opportunity and (not best_opportunity or opportunity['profit_percent'] > best_opportunity['profit_percent']):
                    best_opportunity = opportunity
            
            if best_opportunity and best_opportunity['profit_percent'] > MIN_PROFIT_PERCENT:
                token_name = token_names.get(best_opportunity['token'], best_opportunity['token'])
                logger.info(f"Profitable opportunity found: {best_opportunity['profit_percent']:.2f}% with {token_name}")
                
                # Execute the opportunity
                should_execute = AUTO_EXECUTE
                
                if not AUTO_EXECUTE:
                    user_input = input(f"Execute this {best_opportunity['profit_percent']:.2f}% arbitrage with {token_name}? (y/n): ")
                    should_execute = user_input.lower() == 'y'
                
                if should_execute:
                    execution_count += 1
                    logger.info(f"Executing arbitrage #{execution_count}")
                    success = await execute_flash_loan_arbitrage(best_opportunity)
                    
                    if success:
                        logger.info(f"Arbitrage #{execution_count} successful!")
                    else:
                        logger.error(f"Arbitrage #{execution_count} failed!")
            else:
                if best_opportunity:
                    logger.info(f"Best opportunity found: {best_opportunity['profit_percent']:.2f}% (below threshold)")
                else:
                    logger.info("No arbitrage opportunities found")
            
            logger.info(f"Waiting {SCAN_INTERVAL} seconds until next scan...")
            await asyncio.sleep(SCAN_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("Scanning stopped by user")
    except Exception as e:
        logger.error(f"Error in continuous scanning: {str(e)}")
        logger.info("Restarting scan in 60 seconds...")
        await asyncio.sleep(60)
        await scan_continuously()  # Restart scanning

async def main():
    global AUTO_EXECUTE, FLASH_LOAN_AMOUNT
    
    logger.info("="*50)
    logger.info("STARTING FLASH LOAN ARBITRAGE BOT")
    logger.info("="*50)
    
    logger.info(f"Connected to Ethereum mainnet: {w3.is_connected()}")
    logger.info(f"Account: {account.address}")
    
    # Check balance for gas
    eth_balance = w3.eth.get_balance(account.address)
    logger.info(f"ETH Balance: {w3.from_wei(eth_balance, 'ether')} ETH")
    
    if eth_balance < w3.to_wei(0.01, 'ether'):
        logger.warning("ETH balance is low. You need ETH to pay for gas.")
        if input("Continue anyway? (y/n): ").lower() != 'y':
            return
    
    # Verify contract deployment
    code = w3.eth.get_code(ARBITRAGER_ADDRESS)
    if len(code) <= 2:
        logger.error(f"Arbitrager contract not deployed at {ARBITRAGER_ADDRESS}")
        return
    else:
        logger.info("Arbitrager contract verified as deployed")
    
    # Select operation mode
    print("\nOperation Modes:")
    print("1. Continuous Scan (scan continuously until stopped)")
    print("2. Change Flash Loan Amount")
    print("3. Change Minimum Profit Threshold")
    print("4. Change Gas Price Limit")
    
    mode = input("Select mode (1/2/3/4): ")
    
    if mode == "1":
        # Do you want auto-execution?
        auto = input("Auto-execute trades without confirmation? (y/n): ")
        AUTO_EXECUTE = auto.lower() == 'y'
        
        # Customize flash loan amount
        amount_input = input(f"Enter flash loan amount in ETH [{FLASH_LOAN_AMOUNT}]: ")
        if amount_input.strip():
            FLASH_LOAN_AMOUNT = float(amount_input)
        
        # Start continuous scanning
        await scan_continuously()
        
    elif mode == "2":
        # Change flash loan amount
        new_amount = float(input("Enter new flash loan amount in ETH: "))
        FLASH_LOAN_AMOUNT = new_amount
        logger.info(f"Flash loan amount updated to {FLASH_LOAN_AMOUNT} ETH")
    
    elif mode == "3":
        # Change minimum profit threshold
        global MIN_PROFIT_PERCENT
        new_threshold = float(input(f"Enter new minimum profit threshold % [{MIN_PROFIT_PERCENT}]: "))
        MIN_PROFIT_PERCENT = new_threshold
        logger.info(f"Minimum profit threshold updated to {MIN_PROFIT_PERCENT}%")
    
    elif mode == "4":
        # Change gas price limit
        global MAX_GAS_PRICE
        new_gas_limit = float(input(f"Enter new maximum gas price in gwei [{MAX_GAS_PRICE}]: "))
        MAX_GAS_PRICE = new_gas_limit
        logger.info(f"Maximum gas price updated to {MAX_GAS_PRICE} gwei")
    
    logger.info("Bot operation complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
