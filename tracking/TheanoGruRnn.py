import theano as Theano
import theano.tensor as Tensor
import numpy as NP
import numpy.random as RNG
import theano.tensor.nnet as NN

from collections import OrderedDict



class TheanoGruRnn(object):
    
    fitFunc = None
    forwardFunc = None
    params = None
    seqLength = None
    
    def __init__(self, inputDim, stateDim, batchSize, seqLength, zeroTailFc):
        ### Computed hyperparameters begin
        self.inputDim = inputDim + 4
        self.seqLength = seqLength
        self.fitFunc, self.forwardFunc, self.params = self.buildModel(batchSize, inputDim, stateDim, zeroTailFc)

    
    def fit(self, data, label):
        return self.fitFunc(self.seqLength, data, label[:, 0, :], label)
      
        
    def forward(self, data, label):
        cost, output = self.forwardFunc(self.seqLength, data, label[:, 0, :], label)
        return output
    
    
    def loadModel(self, modelPath):
        f = open(modelPath, "rb")
        param_saved = cPickle.load(f)
        for _p, p in zip(self.params, param_saved):
            _p.set_value(p)
      
        
    def getTensor(self, name, dtype, dim):
        if dtype == None:
            dtype = Theano.config.floatX
        
        return Tensor.TensorType(dtype, [False] * dim, name=name)()
        
    
    def buildModel(self, batchSize, inputDim, stateDim, zeroTailFc):
        print 'Building network'
        
        # imgs: of shape (batchSize, seq_len, nr_channels, img_rows, img_cols)
        imgs = self.getTensor("images", Theano.config.floatX, 5)
        starts = Tensor.matrix()
    
        Wr, Ur, br, Wz, Uz, bz, Wg, Ug, bg, W_fc2, b_fc2 = self.init_params(inputDim, stateDim, zeroTailFc)
        params = [Wr, Ur, br, Wz, Uz, bz, Wg, Ug, bg, W_fc2, b_fc2]
    
        # Move the time axis to the top
        sc, _ = Theano.scan(self.step, sequences=[imgs.dimshuffle(1, 0, 2, 3, 4)], outputs_info=[starts, Tensor.zeros((batchSize, stateDim))], non_sequences=params+[batchSize,inputDim - 4], strict=True)
    
        bbox_seq = sc[0].dimshuffle(1, 0, 2)
    
        # targets: of shape (batch_size, seq_len, 4)
        targets = self.getTensor("targets", Theano.config.floatX, 3)
        seq_len_scalar = Tensor.scalar()
    
        cost = ((targets - bbox_seq) ** 2).sum() / batchSize / seq_len_scalar
    
        print 'Building optimizer'
    
        fitFunc = Theano.function([seq_len_scalar, imgs, starts, targets], [cost, bbox_seq], updates=self.rmsprop(cost, params), allow_input_downcast=True)
        forwardFunc = Theano.function([seq_len_scalar, imgs, starts, targets], [cost, bbox_seq], allow_input_downcast=True)
        
        return fitFunc, forwardFunc, params
    
    
    def init_params(self, inputDim, stateDim, zeroTailFc):
        ### NETWORK PARAMETERS BEGIN
        Wr = Theano.shared(self.glorot_uniform((inputDim, stateDim)), name='Wr')
        Ur = Theano.shared(self.orthogonal((stateDim, stateDim)), name='Ur')
        br = Theano.shared(NP.zeros((stateDim,), dtype=Theano.config.floatX), name='br')
        Wz = Theano.shared(self.glorot_uniform((inputDim, stateDim)), name='Wz')
        Uz = Theano.shared(self.orthogonal((stateDim, stateDim)), name='Uz')
        bz = Theano.shared(NP.zeros((stateDim,), dtype=Theano.config.floatX), name='bz')
        Wg = Theano.shared(self.glorot_uniform((inputDim, stateDim)), name='Wg')
        Ug = Theano.shared(self.orthogonal((stateDim, stateDim)), name='Ug')
        bg = Theano.shared(NP.zeros((stateDim,), dtype=Theano.config.floatX), name='bg')
        W_fc2 = Theano.shared(self.glorot_uniform((stateDim, 4)) if not zeroTailFc else NP.zeros((stateDim, 4), dtype=Theano.config.floatX), name='W_fc2')
        b_fc2 = Theano.shared(NP.zeros((4,), dtype=Theano.config.floatX), name='b_fc2')
        ### NETWORK PARAMETERS END
    
        return Wr, Ur, br, Wz, Uz, bz, Wg, Ug, bg, W_fc2, b_fc2
    
    
    def rmsprop(self, cost, params, lr=0.0005, rho=0.9, epsilon=1e-6):
        '''
        Borrowed from keras, no constraints, though
        '''
        updates = OrderedDict()
        grads = Theano.grad(cost, params)
        acc = [Theano.shared(NP.zeros(p.get_value().shape, dtype=Theano.config.floatX)) for p in params]
        for p, g, a in zip(params, grads, acc):
            new_a = rho * a + (1 - rho) * g ** 2
            updates[a] = new_a
            new_p = p - lr * g / Tensor.sqrt(new_a + epsilon)
            updates[p] = new_p
    
        return updates  
    
    
    def step(self, act1, prev_bbox, state, Wr, Ur, br, Wz, Uz, bz, Wg, Ug, bg, W_fc2, b_fc2, batch_size, conv_output_dim):
        # of (batch_size, nr_filters, some_rows, some_cols)
        flat1 = Tensor.reshape(act1, (batch_size, conv_output_dim))
        gru_in = Tensor.concatenate([flat1, prev_bbox], axis=1)
        gru_z = NN.sigmoid(Tensor.dot(gru_in, Wz) + Tensor.dot(state, Uz) + bz)
        gru_r = NN.sigmoid(Tensor.dot(gru_in, Wr) + Tensor.dot(state, Ur) + br)
        gru_h_ = Tensor.tanh(Tensor.dot(gru_in, Wg) + Tensor.dot(gru_r * state, Ug) + bg)
        gru_h = (1-gru_z) * state + gru_z * gru_h_
        bbox = Tensor.tanh(Tensor.dot(gru_h, W_fc2) + b_fc2)
        
        return bbox, gru_h
    
    
    def glorot_uniform(self, shape):
        '''
        Borrowed from keras
        '''
        fan_in, fan_out = self.get_fans(shape)
        s = NP.sqrt(6. / (fan_in + fan_out))
        return NP.cast[Theano.config.floatX](RNG.uniform(low=-s, high=s, size=shape))
    
    
    def get_fans(self, shape):
        '''
        Borrowed from keras
        '''
        fan_in = shape[0] if len(shape) == 2 else NP.prod(shape[1:])
        fan_out = shape[1] if len(shape) == 2 else shape[0]
        return fan_in, fan_out
    
    
    def orthogonal(self, shape, scale=1.1):
        '''
        Borrowed from keras
        '''
        flat_shape = (shape[0], NP.prod(shape[1:]))
        a = RNG.normal(0, 1, flat_shape)
        u, _, v = NP.linalg.svd(a, full_matrices=False)
        q = u if u.shape == flat_shape else v
        q = q.reshape(shape)
        
        return NP.cast[Theano.config.floatX](q)