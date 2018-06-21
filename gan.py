import argparse
import os
import numpy as np
import math

import torchvision.transforms as transforms
from torchvision.utils import save_image

from torch.utils.data import DataLoader
from torchvision import datasets
from torchvision.datasets import MNIST
from torch.autograd import Variable

import torch.nn as nn
import torch.nn.functional as F
import torch
from copy import deepcopy
from sampler import subsample_dataset, append_dataset

os.makedirs('images', exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument('--n_epochs', type=int, default=50000, help='number of epochs of training')
parser.add_argument('--batch_size', type=int, default=10, help='size of the batches')
parser.add_argument('--lr', type=float, default=0.0001, help='adam: learning rate')
parser.add_argument('--b1', type=float, default=0.5, help='adam: decay of first order momentum of gradient')
parser.add_argument('--b2', type=float, default=0.999, help='adam: decay of first order momentum of gradient')
parser.add_argument('--n_cpu', type=int, default=8, help='number of cpu threads to use during batch generation')
parser.add_argument('--latent_dim', type=int, default=100, help='dimensionality of the latent space')
parser.add_argument('--img_size', type=int, default=28, help='size of each image dimension')
parser.add_argument('--channels', type=int, default=1, help='number of image channels')
parser.add_argument('--sample_interval', type=int, default=400, help='interval betwen image samples')
opt = parser.parse_args()
print(opt)

img_shape = (opt.channels, opt.img_size, opt.img_size)
print(img_shape)
# print(np.prod(img_shape))

cuda = True if torch.cuda.is_available() else False


class Generator(nn.Module):
    def __init__(self):
        super(Generator, self).__init__()

        def block(in_feat, out_feat, normalize=True):
            layers = [nn.Linear(in_feat, out_feat)]
            if normalize:
                layers.append(nn.BatchNorm1d(out_feat, 0.8))
            layers.append(nn.LeakyReLU(0.2, inplace=True))
            return layers

        self.model = nn.Sequential(
            *block(opt.latent_dim, 128, normalize=False),
            *block(128, 256),
            *block(256, 512),
            *block(512, 1024),
            nn.Linear(1024, int(np.prod(img_shape))),
            nn.Tanh()
        )

    def forward(self, z):
        img = self.model(z)
        img = img.view(img.size(0), *img_shape)
        return img


class Discriminator(nn.Module):
    def __init__(self):
        super(Discriminator, self).__init__()

        self.model = nn.Sequential(
            nn.Linear(int(np.prod(img_shape)), 512),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Linear(512, 256),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Linear(256, 1),
            nn.Sigmoid()
        )

    def forward(self, img):
        img_flat = img.view(img.size(0), -1)
        validity = self.model(img_flat)

        return validity


# Configure data loader

train_dataset = MNIST('../data/MNIST', train=True, download=True,
                      transform=transforms.Compose([
                          transforms.ToTensor(),
                          # transforms.Normalize((0.1307,), (0.3081,))
                          transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                      ]))

train_dataset_sampled = subsample_dataset(train_dataset, 0)

dataloader = torch.utils.data.DataLoader(train_dataset_sampled, batch_size=opt.batch_size, shuffle=True)


def generate_gan_model(train_dataset, parser, cuda, num_generate, label):
    train_dataset_sampled = subsample_dataset(train_dataset, label)

    dataloader = torch.utils.data.DataLoader(train_dataset_sampled, batch_size=opt.batch_size, shuffle=True)

    train_dataset_generate = deepcopy(train_dataset_sampled)
    feature = train_dataset_generate.train_data.numpy()
    labels = train_dataset_generate.train_labels.numpy()

    # Initialize generator and discriminator
    generator = Generator()
    discriminator = Discriminator()

    # Loss function
    adversarial_loss = torch.nn.BCELoss()

    if cuda:
        generator.cuda()
        discriminator.cuda()
        adversarial_loss.cuda()

    # ----------
    #  Training
    # ----------

    # Optimizers
    optimizer_G = torch.optim.Adam(generator.parameters(), lr=opt.lr, betas=(opt.b1, opt.b2))
    optimizer_D = torch.optim.Adam(discriminator.parameters(), lr=opt.lr, betas=(opt.b1, opt.b2))

    Tensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor

    for epoch in range(parser.n_epochs):
        for i, (imgs, _) in enumerate(dataloader):

            # Adversarial ground truths
            valid = Variable(Tensor(imgs.size(0), 1).fill_(1.0), requires_grad=False)
            fake = Variable(Tensor(imgs.size(0), 1).fill_(0.0), requires_grad=False)

            # Configure input
            real_imgs = Variable(imgs.type(Tensor))

            # -----------------
            #  Train Generator
            # -----------------

            optimizer_G.zero_grad()

            # Sample noise as generator input
            z = Variable(Tensor(np.random.normal(0, 1, (imgs.shape[0], parser.latent_dim))))
            print("shape z: ", imgs.shape[0])

            # Generate a batch of images
            gen_imgs = generator(z)

            # Loss measures generator's ability to fool the discriminator
            g_loss = adversarial_loss(discriminator(gen_imgs), valid)

            g_loss.backward()
            optimizer_G.step()

            # ---------------------
            #  Train Discriminator
            # ---------------------

            optimizer_D.zero_grad()

            # Measure discriminator's ability to classify real from generated samples
            real_loss = adversarial_loss(discriminator(real_imgs), valid)
            fake_loss = adversarial_loss(discriminator(gen_imgs.detach()), fake)
            d_loss = (real_loss + fake_loss) / 2

            d_loss.backward()
            optimizer_D.step()

            print("[Epoch %d/%d] [Batch %d/%d] [D loss: %f] [G loss: %f]" % (epoch, parser.n_epochs, i, len(dataloader),
                                                                             d_loss.item(), g_loss.item()))

            batches_done = epoch * len(dataloader) + i
            if batches_done % parser.sample_interval == 0:
                save_image(gen_imgs.data[:25], 'images/%d.png' % batches_done, nrow=5, normalize=True)

    feature_new = []
    label_new = []

    for idx in range(num_generate):
        # Sample noise as generator input
        z = Variable(Tensor(np.random.normal(0, 1, (opt.batch_size, opt.latent_dim))))
        # Generate a batch of images
        gen_imgs = generator(z)
        save_image(gen_imgs.data, 'images/gan_%d.png' % idx, nrow=5, normalize=True)
        gen_imgs = gen_imgs.data.cpu().numpy()

        feature_new.append(gen_imgs[:, 0])
        label_new.append(np.asarray([labels[0]] * gen_imgs.shape[0]))
    feature_new = np.concatenate(feature_new)
    label_new = np.concatenate(label_new)
    assert feature_new.shape[0] == label_new.shape[0]
    feature = np.concatenate((feature, feature_new))
    labels = np.concatenate((labels, label_new))

    return feature, labels


# training
print("training")
num_generate = 95
label = 0
feature_merge = []
labels_merge = []

feature, labels = generate_gan_model(train_dataset, opt, cuda, num_generate, label)

feature_merge.append(feature)
labels_merge.append(labels)
feature_merge = np.concatenate(feature_merge)
labels_merge = np.concatenate(labels_merge)

print(feature_merge.shape)
print(labels_merge.shape)
# train_dataset = append_dataset(train_dataset_sampled, feature, labels)
#
# print(train_dataset)
