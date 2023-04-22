"""
@file CommonVAE.py

Holds the encoder/decoder architectures that are shared across the NSSM works
"""
import torch.nn as nn

from utils.layers import Flatten, UnFlatten


class LatentStateEncoder(nn.Module):
    def __init__(self, z_amort, num_filters, num_channels, latent_dim):
        """
        Holds the convolutional encoder that takes in a sequence of images and outputs the
        initial state of the latent dynamics
        :param z_amort: how many GT steps are used in initialization
        :param num_filters: base convolutional filters, upscaled by 2 every layer
        :param num_channels: how many image color channels there are
        :param latent_dim: dimension of the latent dynamics
        """
        super(LatentStateEncoder, self).__init__()
        self.z_amort = z_amort
        self.num_channels = num_channels

        # Encoder, q(z_0 | x_{0:z_amort})
        self.initial_encoder = nn.Sequential(
            nn.Conv2d(z_amort, num_filters, kernel_size=5, stride=2, padding=(2, 2)),  # 14,14
            nn.BatchNorm2d(num_filters),
            nn.LeakyReLU(),
            nn.Conv2d(num_filters, num_filters * 2, kernel_size=5, stride=2, padding=(2, 2)),  # 7,7
            nn.BatchNorm2d(num_filters * 2),
            nn.LeakyReLU(),
            nn.Conv2d(num_filters * 2, num_filters * 4, kernel_size=5, stride=2, padding=(2, 2)),
            nn.BatchNorm2d(num_filters * 4),
            nn.LeakyReLU(),
            nn.AvgPool2d(4),
            Flatten()
        )

        self.initial_encoder_out = nn.Linear(num_filters * 4, latent_dim)
        self.out_act = nn.Tanh()

    def forward(self, x):
        """
        Handles getting the initial state given x and saving the distributional parameters
        :param x: input sequences [BatchSize, GenerationLen * NumChannels, H, W]
        :return: z0 over the batch [BatchSize, LatentDim]
        """
        z0 = self.initial_encoder_out(self.initial_encoder(x[:, :self.z_amort]))
        return self.out_act(z0)


class EmissionDecoder(nn.Module):
    def __init__(self, batch_size, generation_len, dim, num_filters, num_channels, latent_dim):
        """
        Holds the convolutional decoder that takes in a batch of individual latent states and
        transforms them into their corresponding data space reconstructions
        """
        super(EmissionDecoder, self).__init__()
        self.batch_size = batch_size
        self.generation_len = generation_len
        self.dim = dim
        self.num_channels = num_channels

        # Variable that holds the estimated output for the flattened convolution vector
        self.conv_dim = num_filters * 4 ** 3

        # Emission model handling z_i -> x_i
        self.decoder = nn.Sequential(
            # Transform latent vector into 4D tensor for deconvolution
            nn.Linear(latent_dim, self.conv_dim),
            nn.BatchNorm1d(self.conv_dim),
            nn.LeakyReLU(),
            UnFlatten(4),

            # Perform de-conv to output space
            nn.ConvTranspose2d(self.conv_dim // 16, num_filters * 4, kernel_size=4, stride=1, padding=(0, 0)),
            nn.BatchNorm2d(num_filters * 4),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(num_filters * 4, num_filters * 2, kernel_size=5, stride=2, padding=(1, 1)),
            nn.BatchNorm2d(num_filters * 2),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(num_filters * 2, num_filters, kernel_size=5, stride=2, padding=(1, 1), output_padding=(1, 1)),
            nn.BatchNorm2d(num_filters),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(num_filters, 1, kernel_size=5, stride=1, padding=(2, 2)),
            nn.Sigmoid(),
        )

    def forward(self, zts):
        """
        Handles decoding a batch of individual latent states into their corresponding data space reconstructions
        :param zts: latent states [BatchSize * GenerationLen, LatentDim]
        :return: data output [BatchSize, GenerationLen, NumChannels, H, W]
        """
        # Flatten to [BS * SeqLen, -1]
        zts = zts.contiguous().view([zts.shape[0] * zts.shape[1], -1])

        # Decode back to image space
        x_rec = self.decoder(zts)

        # Reshape to image output
        x_rec = x_rec.view([self.batch_size, x_rec.shape[0] // self.batch_size, self.dim, self.dim])
        return x_rec
