# credits to Mahmoud Asem 2022 @KAIST
# functions that operate on arrays
# higher accuracy finite difference gradient might require
# setting jax.config.update("jax_enable_x64", True)

from __future__ import annotations

import functools as ft
from itertools import combinations

import jax
import jax.numpy as jnp

from finitediffx._src.utils import (
    _check_and_return,
    _generate_backward_offsets,
    _generate_central_offsets,
    _generate_forward_offsets,
    generate_finitediff_coeffs,
)

__all__ = (
    "hessian",
    "difference",
    "gradient",
    "jacobian",
    "laplacian",
    "curl",
    "divergence",
)


def _central_difference(
    x: jnp.ndarray,
    *,
    axis: int,
    left_coeffs,
    center_coeffs,
    right_coeffs,
    left_offsets,
    center_offsets,
    right_offsets,
):
    size = x.shape[axis]
    sliced = ft.partial(jax.lax.slice_in_dim, x, axis=axis)

    # use central difference for interior points
    left_x = sum(
        coeff * sliced(offset, offset - center_offsets[0])
        for offset, coeff in zip(left_offsets, left_coeffs)
    )

    right_x = sum(
        coeff * sliced(size + (offset - center_offsets[-1]), size + (offset))
        for offset, coeff in zip(right_offsets, right_coeffs)
    )

    center_x = sum(
        coeff * sliced(offset - center_offsets[0], size + (offset - center_offsets[-1]))
        for offset, coeff in zip(center_offsets, center_coeffs)
    )

    return jnp.concatenate([left_x, center_x, right_x], axis=axis)


def _forward_difference(
    x,
    *,
    axis,
    left_coeffs,
    right_coeffs,
    left_offsets,
    right_offsets,
):
    size = x.shape[axis]
    sliced = ft.partial(jax.lax.slice_in_dim, x, axis=axis)

    left_x = sum(
        coeff * sliced(offset, offset + left_offsets[-1] + size % 2)
        for offset, coeff in zip(left_offsets, left_coeffs)
    )

    right_x = sum(
        coeff * sliced(size + (offset - left_offsets[-1]), size + (offset))
        for offset, coeff in zip(right_offsets, right_coeffs)
    )

    return jnp.concatenate([left_x, right_x], axis=axis)


@ft.partial(jax.jit, static_argnames=("accuracy", "axis", "derivative"))
def difference(
    array: jnp.ndarray,
    *,
    axis: int = 0,
    accuracy: int = 1,
    step_size: float | jnp.ndarray = 1,
    derivative: int = 1,
) -> jnp.ndarray:
    """Compute the finite difference derivative along a given axis with a given accuracy
    using central difference for interior points and forward/backward difference for boundary points
    Similar to np.gradient, but with the option to specify accuracy, derivative and step size
    See: https://github.com/google/jax/blob/main/jax/_src/numpy/lax_numpy.py

    Args:
        x: input array
        axis: axis along which to compute the gradient. Default is 0
        accuracy: accuracy order of the gradient. Default is 1
        step_size: step size. Default is 1
        derivative: derivative order of the gradient. Default is 1
    Returns:
        Finite difference derivative along the given axis

    Example:
        # dydx of a 2D array
        >>> x, y = [jnp.linspace(0, 1, 100)] * 2
        >>> dx, dy = x[1] - x[0], y[1] - y[0]
        >>> X, Y = jnp.meshgrid(x, y, indexing="ij")
        >>> F =  jnp.sin(X) * jnp.cos(Y)
        >>> dFdX = difference(F, step_size=dx, axis=0, accuracy=3)
        >>> dFdXdY = difference(dFdX, step_size=dy, axis=1, accuracy=3)

        # 1d finite difference derivative
        >>> x = jnp.array([1.2, 1.3, 2.2, 3., 4.5, 5.5, 6., 7., 8., 20.])
        >>> difference(x, accuracy=1)
        [ 0.0999999  0.5        0.85       1.15       1.25       0.75 0.75       1.         6.5       12.       ]


        # apply forward difference to the first element with accuracy 1
        x_1 = 1.3-1.2 = 0.1

        # apply central difference to interior elements with accuracy 2
        x_2 = (2.2-1.2)/2 = 0.5
        x_3 = (3.-1.3)/2 = 0.85
        x_4 = (4.5-2.2)/2 = 1.15
        x_5 = (5.5-3.)/2 = 1.25
        x_6 = (6.-4.5)/2 = 0.75
        x_7 = (7.-5.5)/2 = 0.75
        x_8 = (8.-6.)/2 = 1.
        x_9 = (20.-7.)/2 = 6.5

        # apply backward difference to the last element with accuracy 1
        x_10 = 20.-8. = 12.
    """
    size = array.shape[axis]

    center_offsets = _generate_central_offsets(derivative, accuracy + 1)
    center_coeffs = generate_finitediff_coeffs(center_offsets, derivative)

    left_offsets = _generate_forward_offsets(derivative, accuracy)
    left_coeffs = generate_finitediff_coeffs(left_offsets, derivative)

    right_offsets = _generate_backward_offsets(derivative, accuracy)
    right_coeffs = generate_finitediff_coeffs(right_offsets, derivative)

    # use central difference for interior points and
    # forward/backward difference for boundary points
    if size >= len(center_offsets):
        return _central_difference(
            array,
            axis=axis,
            left_coeffs=left_coeffs,
            center_coeffs=center_coeffs,
            right_coeffs=right_coeffs,
            left_offsets=left_offsets,
            center_offsets=center_offsets,
            right_offsets=right_offsets,
        ) / (step_size**derivative)

    # if size < len(center_offsets), use forward/backward
    # difference for interior points
    if size >= len(left_offsets):
        return _forward_difference(
            array,
            axis=axis,
            left_coeffs=left_coeffs,
            right_coeffs=right_coeffs,
            left_offsets=left_offsets,
            right_offsets=right_offsets,
        ) / (step_size**derivative)

    msg = f"Size of the array along axis {axis} is smaller than the number of points required"
    msg += f" for the accuracy {accuracy} and derivative {derivative} requested"
    msg += f".\nSize must be larger than {len(left_offsets)}, but got {size}"
    raise ValueError(msg)


@ft.partial(jax.jit, static_argnames=("accuracy"))
def gradient(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] | jnp.ndarray = 1,
) -> jnp.ndarray:
    """Compute the ???F of input array where F is a scalar function of x and
    returns vectors of the same shape as x stacked along the first axis.

    Args:
        x: input array
        accuracy: accuracy order of the gradient. Default is 1, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis

    Index notation : dF/dxi

    Example:
        # ???F of a 2D array
        >>> x, y = [jnp.linspace(0, 1, 100)] * 2
        >>> dx, dy = x[1] - x[0], y[1] - y[0]
        >>> X, Y = jnp.meshgrid(x, y, indexing="ij")
        >>> Z = X**2 + Y**3
        >>> dZdX , dZdY = gradient(Z, step_size=(dx,dy))
        >>> dZdx_true, dZdy_true= 2*X , 3*Y**2
        >>> numpy.testing.assert_allclose(dZdx, dZdx_true, atol=1e-4)
        >>> numpy.testing.assert_allclose(dZdy, dZdy_true, atol=1e-4)
    """
    accuracy = _check_and_return(accuracy, array.ndim, "accuracy")
    step_size = _check_and_return(step_size, array.ndim, "step_size")

    return jnp.stack(
        [
            difference(array, accuracy=acc, step_size=step, derivative=1, axis=axis)
            for axis, (acc, step) in enumerate(zip(accuracy, step_size))
        ],
        axis=0,
    )


@ft.partial(jax.jit, static_argnames=("accuracy"))
def jacobian(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] | jnp.ndarray = 1,
) -> jnp.ndarray:
    """Compute the ???Fi/???xj of input array where F is a vector function of x and
    returns vectors of the same shape as x stacked along the first axis.

    Args:
        x: input array
        accuracy: accuracy order of the gradient. Default is 1, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis

    Index notation: ???Fi/???xj

    Example:
        # F: R^2 -> R^2
        # F = [ x^2*y, 5x+siny ]
        # JF = [ [2xy, x^2], [5, cos(y)] ]
        >>> with jax.experimental.enable_x64():
        ...    x, y = [jnp.linspace(-1, 1, 100)] * 2
        ...    dx, dy = x[1] - x[0], y[1] - y[0]
        ...    X, Y = jnp.meshgrid(x, y, indexing="ij")
        ...    F1 = X**2 * Y
        ...    F2 = 5 * X + jnp.sin(Y)
        ...    F = jnp.stack([F1, F2], axis=0)
        ...    JF = jacobian(F, accuracy=4, step_size=(dx, dy))
        ...    JF_true = jnp.array([[2 * X * Y, X**2], [5*jnp.ones_like(X), jnp.cos(Y)]])
        ...    npt.assert_allclose(JF, JF_true, atol=1e-7)
    """
    accuracy = _check_and_return(accuracy, array.ndim - 1, "accuracy")
    step_size = _check_and_return(step_size, array.ndim - 1, "step_size")

    return jnp.stack(
        [gradient(xi, accuracy=accuracy, step_size=step_size) for xi in array], axis=0
    )


@ft.partial(jax.jit, static_argnames=("accuracy", "keepdims"))
def divergence(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] = 1,
    keepdims: bool = True,
) -> jnp.ndarray:
    """Compute the ???.F of input array where F is a vector field whose components are the first axis of x
    and returns a scalar field

    Args:
        x: input array where the leading axis is the dimension of the vector field
        accuracy: accuracy order of the gradient. Default is 1, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis
        keepdims: whether to keep the leading dimension. Default is True.

    Index notation: dFi/dxi

    Example:
        # ???.F of a 2D array
        >>> x, y = [jnp.linspace(0, 1, 100)] * 2
        >>> dx, dy = x[1] - x[0], y[1] - y[0]
        >>> X, Y = jnp.meshgrid(x, y, indexing="ij")
        >>> F1 = X**2 + Y**3
        >>> F2 = X**4 + Y**3
        >>> F = jnp.stack([F1, F2], axis=0) # 2D vector field F = (F1, F2)
        >>> divZ = divergence(F,step_size=(dx,dy), accuracy=7, keepdims=False)
        >>> divZ_true = 2*X + 3*Y**2  # (dF1/dx) + (dF2/dy)
        >>> numpy.testing.assert_allclose(divZ, divZ_true, atol=5e-4)
    """
    accuracy = _check_and_return(accuracy, array.ndim - 1, "accuracy")
    step_size = _check_and_return(step_size, array.ndim - 1, "step_size")

    result = sum(
        difference(array[axis], accuracy=acc, step_size=step, derivative=1, axis=axis)
        for axis, (acc, step) in enumerate(zip(accuracy, step_size))
    )

    if keepdims:
        return jnp.expand_dims(result, axis=0)
    return result


def hessian(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 2,
    step_size: float | tuple[float, ...] | jnp.ndarray = 1,
) -> jnp.ndarray:
    """Compute hessian of F: R^m -> R

    Args:
        x: input array
        accuracy: accuracy order of the gradient. Default is 2, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis

    Index notation: d2F/dxij

    Example:
        >>> x, y = [jnp.linspace(-1, 1, 100)] * 2
        >>> dx, dy = x[1] - x[0], y[1] - y[0]
        >>> X, Y = jnp.meshgrid(x, y, indexing="ij")

        >>> F = X**2 * Y
        >>> H = hessian(F, accuracy=4, step_size=(dx, dy))
        >>> H_true = jnp.array([[2 * Y, 2 * X], [2 * X, jnp.zeros_like(X)]])
        >>> npt.assert_allclose(H, H_true, atol=1e-7)
    """
    accuracy = _check_and_return(accuracy, array.ndim, "accuracy")
    step_size = _check_and_return(step_size, array.ndim, "step_size")
    axes = tuple(range(array.ndim))
    F = dict()

    # diag
    for axis in range(array.ndim):
        F[2 * axis] = difference(
            array,
            accuracy=accuracy[axis],
            step_size=step_size[axis],
            axis=axis,
            derivative=2,
        )

    # off-diag
    for ax1, ax2 in combinations(axes, 2):
        F[ax1 + ax2] = difference(
            difference(
                array, accuracy=accuracy[ax1], step_size=step_size[ax1], axis=ax1
            ),
            accuracy=accuracy[ax2],
            step_size=step_size[ax2],
            axis=ax2,
        )

    return jnp.stack(
        [
            jnp.stack([F[ax1 + ax2] for ax2 in range(array.ndim)])
            for ax1 in range(array.ndim)
        ]
    )


@ft.partial(jax.jit, static_argnames=("accuracy"))
def laplacian(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] | jnp.ndarry = 1,
) -> jnp.ndarray:
    """Compute the ??F of input array.
    Args:
        x: input array
        accuracy: accuracy order of the gradient. Default is 1, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis

    Index notation: d2F/dxi2
    Example:
        # ??F array
        >>> x, y = [jnp.linspace(0, 1, 100)] * 2
        >>> dx, dy = x[1] - x[0], y[1] - y[0]
        >>> X, Y = jnp.meshgrid(x, y, indexing="ij")
        >>> Z = X**4 + Y**3
        >>> laplacianZ = laplacian(Z, step_size=(dx,dy))
        >>> laplacianZ_true = 12*X**2 + 6*Y
        >>> numpy.testing.assert_allclose(laplacianZ, laplacianZ_true, atol=1e-4)
    """
    accuracy = _check_and_return(accuracy, array.ndim, "accuracy")
    step_size = _check_and_return(step_size, array.ndim, "step_size")

    return sum(
        difference(array, accuracy=acc, step_size=step, derivative=2, axis=axis)
        for axis, (acc, step) in enumerate(zip(accuracy, step_size))
    )


def _curl_2d(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] | jnp.ndarray = 1,
    keepdims: bool = True,
) -> jnp.ndarray:
    """Compute the ?????F of input array where F is a vector field whose components are the first axis of x
    and returns a vector field

    Index notation: ??ijk dFk/dxj

    Args:
        x: input array where the leading axis is the dimension of the vector field
        accuracy: accuracy order of the gradient. Default is 1, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis
        keepdims: whether to keep the leading dimension of the vector field

    Example:
        >>> x,y = [jnp.linspace(-1,1,50)]*2
        >>> dx,dy = x[1]-x[0],y[1]-y[0]
        >>> X,Y = jnp.meshgrid(x,y, indexing="ij")
        >>> F1 = jnp.sin(Y)
        >>> F2 = jnp.cos(X)
        >>> F = jnp.stack([F1,F2], axis=0)
        >>> curl = curl_2d(F, accuracy=4, step_size=dx)
    """
    dF1dY = difference(array[0], accuracy=accuracy[1], step_size=step_size[1], axis=1)
    dF2dX = difference(array[1], accuracy=accuracy[0], step_size=step_size[0], axis=0)

    result = dF2dX - dF1dY

    if keepdims:
        return jnp.expand_dims(result, axis=0)

    return result


def _curl_3d(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] | jnp.ndarry = 1,
) -> jnp.ndarray:
    dF1dY = difference(array[0], accuracy=accuracy[1], step_size=step_size[1], axis=1)
    dF1dZ = difference(array[0], accuracy=accuracy[2], step_size=step_size[2], axis=2)

    dF2dX = difference(array[1], accuracy=accuracy[0], step_size=step_size[0], axis=0)
    dF2dZ = difference(array[1], accuracy=accuracy[2], step_size=step_size[2], axis=2)

    dF3dX = difference(array[2], accuracy=accuracy[0], step_size=step_size[0], axis=0)
    dF3dY = difference(array[2], accuracy=accuracy[1], step_size=step_size[1], axis=1)

    return jnp.stack(
        [
            dF3dY - dF2dZ,
            dF1dZ - dF3dX,
            dF2dX - dF1dY,
        ],
        axis=0,
    )


@ft.partial(jax.jit, static_argnames=("accuracy", "keepdims"))
def curl(
    array: jnp.ndarray,
    *,
    accuracy: int | tuple[int, ...] = 1,
    step_size: float | tuple[float, ...] | jnp.ndarry = 1,
    keepdims: bool = True,
) -> jnp.ndarray:
    """Compute the ?????F of input array where F is a vector field whose components are the first axis of x
    and returns a vector field

    Index notation: ??ijk dFk/dxj

    Args:
        x: input array where the leading axis is the dimension of the vector field
        accuracy: accuracy order of the gradient. Default is 1, can be a tuple for each axis
        step_size: step size. Default is 1, can be a tuple for each axis
        keepdims: whether to keep the leading dimension of the vector field (only for 2D)

    Example:
        Curl for a 3D vector field is defined as
        F = (F1, F2, F3)
        ?????F = (dF3/dy - dF2/dz, dF1/dz - dF3/dx, dF2/dx - dF1/dy)
        >>> jax.config.update("jax_enable_x64", True)
        >>> x,y,z = [jnp.linspace(0, 1, 100)] * 3
        >>> dx,dy,dz = x[1]-x[0], y[1]-y[0], z[1]-z[0]
        >>> X,Y,Z = jnp.meshgrid(x,y,z, indexing="ij")
        >>> F1 = X**2 + Y**3
        >>> F2 = X**4 + Y**3
        >>> F3 = jnp.zeros_like(F1)
        >>> F = jnp.stack([F1,F2,F3], axis=0)
        >>> curlF = finitediffx.curl(F, step_size=(dx,dy,dz),  accuracy=6)
        >>> curlF_exact = jnp.stack([F1*0,F1*0, 4*X**3 - 3*Y**2], axis=0)
        >>> npt.assert_allclose(curlF, curlF_exact, atol=1e-7)

        Curl of 2D vector field is defined as
        >>> x,y = [jnp.linspace(-1,1,50)]*2
        >>> dx,dy = x[1]-x[0],y[1]-y[0]
        >>> X,Y = jnp.meshgrid(x,y, indexing="ij")
        >>> F1 = jnp.sin(Y)
        >>> F2 = jnp.cos(X)
        >>> F = jnp.stack([F1,F2], axis=0)
        >>> curl = curl_2d(F, accuracy=4, step_size=dx)
    """

    accuracy = _check_and_return(accuracy, array.ndim - 1, "accuracy")
    step_size = _check_and_return(step_size, array.ndim - 1, "step_size")

    if array.ndim == 4 and array.shape[0] == 3:
        return _curl_3d(array, accuracy=accuracy, step_size=step_size)

    if array.ndim == 3 and array.shape[0] == 2:
        return _curl_2d(
            array, accuracy=accuracy, step_size=step_size, keepdims=keepdims
        )

    msg = f"`curl` is only implemented for 2D and 3D vector fields, got {array.ndim}D"
    msg += "for 2D vector fields, the leading axis must have a shape=2, "
    msg += "for 3D vector fields, the leading axis must have a shape=3"
    raise ValueError(msg)
