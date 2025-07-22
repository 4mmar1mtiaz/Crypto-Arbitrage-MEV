// SPDX-License-Identifier: MIT
pragma solidity 0.8.20;

import '@openzeppelin/contracts/token/ERC20/IERC20.sol';
import '@uniswap/v2-periphery/contracts/interfaces/IUniswapV2Router02.sol';
import './Interface/IERC3156FlashBorrower.sol';
import './Interface/IERC3156FlashLender.sol';

contract ArbitrageExecutor is IERC3156FlashBorrower {
    
    enum Direction {
        ROUTER1_ROUTER2,
        ROUTER2_ROUTER1
    }

    struct ExtraData {
        address swapToken;
        Direction direction;
        uint256 deadline;
        uint256 amountRequired;
        address profitReceiver;
        uint256 minAmountSwapToken;
        uint256 minAmountBorrowedToken;
    }
    
    IERC3156FlashLender public immutable lender;
    IUniswapV2Router02 public immutable router1;
    IUniswapV2Router02 public immutable router2;

    constructor(
        IERC3156FlashLender _lender,
        IUniswapV2Router02 _router1,
        IUniswapV2Router02 _router2
    ) {
        lender = _lender;
        router1 = _router1;
        router2 = _router2;
    }

    function onFlashLoan(
        address initiator,
        address borrowedToken,
        uint256 amount,
        uint256 fee,
        bytes calldata data
    ) external override returns (bytes32) {
        require(msg.sender == address(lender), 'FLASH_BORROWER_UNTRUSTED_LENDER');
        require(initiator == address(this), 'FLASH_BORROWER_LOAN_INITIATOR');

        IERC20 borrowedTokenContract = IERC20(borrowedToken);
        ExtraData memory extraData = abi.decode(data, (ExtraData));
        (IUniswapV2Router02 firstRouter, IUniswapV2Router02 secondRouter) = _getRouters(extraData.direction);

        // Call protocol 1
        uint256 amountReceivedSwapToken = _protocolCall(
            firstRouter,
            borrowedToken,
            extraData.swapToken,
            amount,
            extraData.minAmountSwapToken,
            extraData.deadline
        );

        // Call protocol 2
        uint256 amountReceivedBorrowedToken = _protocolCall(
            secondRouter,
            extraData.swapToken,
            borrowedToken,
            amountReceivedSwapToken,
            extraData.minAmountBorrowedToken,
            extraData.deadline
        );

        uint256 repay = amount + fee;

        // Transfer profits
        borrowedTokenContract.transfer(
            extraData.profitReceiver,
            amountReceivedBorrowedToken - repay - extraData.amountRequired
        );

        // Approve lender
        borrowedTokenContract.approve(address(lender), repay);

        return keccak256('ERC3156FlashBorrower.onFlashLoan');
    }

    function executeArbitrage(
        address borrowedToken,
        uint256 amount,
        address[] memory path1,
        address[] memory path2
    ) public {
        require(path1.length >= 2, "Path1 must have at least 2 tokens");
        require(path2.length >= 2, "Path2 must have at least 2 tokens");
        
        ExtraData memory extraData = ExtraData({
            swapToken: path1[1],
            direction: Direction.ROUTER1_ROUTER2,
            deadline: block.timestamp + 3600,
            amountRequired: 0,
            profitReceiver: msg.sender,
            minAmountSwapToken: 0,
            minAmountBorrowedToken: amount
        });
        
        _checkAmountOut(borrowedToken, amount, extraData);
        bytes memory _data = abi.encode(extraData);
        lender.flashLoan(address(this), borrowedToken, amount, _data);
    }

    function _checkAmountOut(
        address borrowedToken,
        uint256 amount,
        ExtraData memory extraData
    ) internal view {
        (IUniswapV2Router02 firstRouter, IUniswapV2Router02 secondRouter) = _getRouters(extraData.direction);

        uint256 amountOutSwapToken = _getAmountOut(firstRouter, borrowedToken, extraData.swapToken, amount);
        uint256 amountOutBorrowedToken = _getAmountOut(secondRouter, extraData.swapToken, borrowedToken, amountOutSwapToken);
        require(amountOutBorrowedToken >= extraData.minAmountBorrowedToken, 'ARBITRAGER_AMOUNT_OUT_TOO_LOW');
    }

    function _getRouters(Direction direction) internal view returns (IUniswapV2Router02, IUniswapV2Router02) {
        if (direction == Direction.ROUTER2_ROUTER1) {
            return (router2, router1);
        }

        return (router1, router2);
    }

    function _getAmountOut(
        IUniswapV2Router02 router,
        address token1,
        address token2,
        uint256 amount
    ) internal view returns (uint256) {
        address[] memory path = new address[](2);
        path[0] = token1;
        path[1] = token2;

        return router.getAmountsOut(amount, path)[1];
    }

    function _protocolCall(
        IUniswapV2Router02 router,
        address token1,
        address token2,
        uint256 amount,
        uint256 minAmount,
        uint256 deadline
    ) internal returns (uint256) {
        address[] memory path = new address[](2);
        path[0] = token1;
        path[1] = token2;
        IERC20(token1).approve(address(router), amount);

        return router.swapExactTokensForTokens(amount, minAmount, path, address(this), deadline)[1];
    }
}
