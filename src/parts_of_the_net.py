import tensorflow as tf
import math


def _nonlinearity(X):
    return tf.nn.relu(X, name='ReLU')


def _dropout(X, rate, is_training):
    keep_prob = tf.constant(
        1.0 - rate, tf.float32,
        [], 'keep_prob'
    )
    result = tf.cond(
        is_training,
        lambda: tf.nn.dropout(X, keep_prob),
        lambda: tf.identity(X),
        name='dropout'
    )
    return result


def _batch_norm(X, is_training):
    return tf.contrib.layers.batch_norm(
        X, is_training=is_training, scale=True, center=True,
        fused=True, scope='batch_norm',
        variables_collections=tf.GraphKeys.MODEL_VARIABLES,
        trainable=True
    )


def _global_average_pooling(X):
    return tf.reduce_mean(
        X, axis=[1, 2],
        name='global_average_pooling'
    )


def _max_pooling(X):
    return tf.nn.max_pool(
        X, [1, 3, 3, 1], [1, 2, 2, 1], 'SAME',
        name='max_pooling'
    )


def _avg_pooling(X):
    return tf.nn.avg_pool(
        X, [1, 3, 3, 1], [1, 2, 2, 1], 'SAME',
        name='avg_pooling'
    )


def _conv(X, filters, kernel=3, stride=1, padding='SAME', trainable=True):

    in_channels = X.shape.as_list()[-1]

    K = tf.get_variable(
        'kernel', [kernel, kernel, in_channels, filters],
        tf.float32, trainable=trainable
    )

    b = tf.get_variable(
        'bias', [filters], tf.float32,
        tf.zeros_initializer(), trainable=trainable
    )

    tf.add_to_collection(tf.GraphKeys.MODEL_VARIABLES, K)
    tf.add_to_collection(tf.GraphKeys.MODEL_VARIABLES, b)

    return tf.nn.bias_add(
        tf.nn.conv2d(X, K, [1, stride, stride, 1], padding), b
    )


def _group_conv(X, filters, groups, kernel=1, stride=1, padding='SAME', trainable=True):

    in_channels = X.shape.as_list()[-1]
    in_channels_per_group = int(in_channels/groups)
    filters_per_group = int(filters/groups)

    K = tf.get_variable(
        'kernel', [kernel, kernel, in_channels_per_group, filters],
        tf.float32, trainable=trainable
    )

    X_channel_splits = tf.split(X, [in_channels_per_group]*groups, axis=-1)
    K_filter_splits = tf.split(K, [filters_per_group]*groups, axis=-1)

    results = []

    for i in range(groups):
        X_split = X_channel_splits[i]
        K_split = K_filter_splits[i]
        results += [tf.nn.conv2d(X_split, K_split, [1, stride, stride, 1], padding)]

    tf.add_to_collection(tf.GraphKeys.MODEL_VARIABLES, K)

    return tf.concat(results, -1)


def _depthwise_conv(X, kernel=3, stride=1, padding='SAME', trainable=True):

    in_channels = X.shape.as_list()[-1]

    W = tf.get_variable(
        'depthwise_kernel', [kernel, kernel, in_channels, 1],
        tf.float32, trainable=trainable
    )

    tf.add_to_collection(tf.GraphKeys.MODEL_VARIABLES, W)

    return tf.nn.depthwise_conv2d(X, W, [1, stride, stride, 1], padding)


def _channel_shuffle(X, groups):
    batch_size, height, width, in_channels = X.shape.as_list()
    in_channels_per_group = int(in_channels/groups)

    shape = tf.stack([batch_size, height, width, groups, in_channels_per_group])
    X = tf.reshape(X, shape)

    X = tf.transpose(X, [0, 1, 2, 4, 3])

    shape = tf.stack([batch_size, height, width, in_channels])
    X = tf.reshape(X, shape)
    return X


def _shufflenet_unit(X, groups, stride=1, trainable=False):

    in_channels = X.shape.as_list()[-1]
    result = X

    with tf.variable_scope('g_conv'):
        result = _group_conv(result, in_channels, groups, trainable=trainablee)
        result = _batch_norm(result)
        result = _nonlinearity(result)

    with tf.variable_scope('channel_shuffle'):
        result = _channel_shuffle(result, groups)

    with tf.variable_scope('dw_conv'):
        result = _depthwise_conv(result, stride=stride, trainable=trainable)
        result = _batch_norm(result)

    with tf.variable_scope('g_conv'):
        result = _group_conv(X, in_channels, groups, trainable=trainable)
        result = _batch_norm(result)

    if stride < 2:
        result = tf.add(result, X)
    else:
        X = _avg_pooling(X)
        result = tf.concat([result, X], -1)

    return _nonlinearity(result)


def _first_shufflenet_unit(X, out_channels, groups, trainable=False):

    in_channels = X.shape.as_list()[-1]
    result = X
    out_channels -= in_channels

    with tf.variable_scope('g_conv'):
        result = _group_conv(result, out_channels, groups=1, trainable=trainablee)
        result = _batch_norm(result)
        result = _nonlinearity(result)

    with tf.variable_scope('channel_shuffle'):
        result = _channel_shuffle(result, groups)

    with tf.variable_scope('dw_conv'):
        result = _depthwise_conv(result, stride=2, trainable=trainable)
        result = _batch_norm(result)

    with tf.variable_scope('g_conv'):
        result = _group_conv(X, out_channels, groups, trainable=trainable)
        result = _batch_norm(result)

    X = _avg_pooling(X)
    result = tf.concat([result, X], -1)

    return _nonlinearity(result)


def _mapping(X, num_classes, is_training):

    # number of shuffle units of stride 1 in each stage
    n_shuffle_units = [3, 7, 3]

    # second stage's number of ouput channels
    if groups == 1:
        out_channels = 144
    elif groups == 2:
        out_channels = 200
    elif groups == 3:
        out_channels = 240
    elif groups == 4:
        out_channels = 272
    elif groups == 8:
        out_channels = 384
    # all 'out_channels' are divisible by corresponding 'groups'

    features_init = tf.contrib.layers.xavier_initializer_conv2d()
    with tf.variable_scope('features', initializer=features_init):

        with tf.variable_scope('conv1'):
            result = _conv(X, 24, (3, 3), strides=(2, 2))
        result = _max_pooling(result)

        with tf.variable_scope('stage2'):
            result = _first_shufflenet_unit(result, out_channels, groups, stride=2)
            for _ in range(n_shuffle_units[0]):
                result = _shufflenet_unit(result, groups)

        with tf.variable_scope('stage3'):
            result = _shufflenet_unit(result, groups, stride=2)
            for _ in range(n_shuffle_units[1]):
                result = _shufflenet_unit(result, groups)

        with tf.variable_scope('stage4'):
            result = _shufflenet_unit(result, groups, stride=2)
            for _ in range(n_shuffle_units[2]):
                result = _shufflenet_unit(result, groups)

    classifier_init = tf.random_normal_initializer(mean=0.0, stddev=0.01)
    with tf.variable_scope('classifier', initializer=classifier_init):

        result = _global_average_pooling(result)
        result = _dropout(result, 0.5, is_training)
        with tf.variable_scope('fc'):
            logits = _affine(result, num_classes)

    return logits


def _add_weight_decay(weight_decay):

    weight_decay = tf.constant(
        weight_decay, tf.float32,
        [], 'weight_decay'
    )

    trainable = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)
    kernels = [v for v in trainable if 'kernel' in v.name]

    for K in kernels:
        l2_loss = tf.multiply(
            weight_decay, tf.nn.l2_loss(K), name='l2_loss'
        )
        tf.losses.add_loss(l2_loss)


def _affine(X, size):
    input_dim = X.shape.as_list()[1]
    maxval = math.sqrt(2.0/input_dim)

    W = tf.get_variable(
        'W', [input_dim, size], tf.float32,
        tf.random_uniform_initializer(-maxval, maxval)
    )

    b = tf.get_variable(
        'b', [size], tf.float32,
        tf.zeros_initializer()
    )

    tf.add_to_collection(tf.GraphKeys.MODEL_VARIABLES, W)
    tf.add_to_collection(tf.GraphKeys.MODEL_VARIABLES, b)

    return tf.nn.bias_add(tf.matmul(X, W), b)