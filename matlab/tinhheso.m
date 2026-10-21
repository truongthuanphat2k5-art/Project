clear; clc; close all;

%% 0. Kiem tra ten script (khong duoc trung ten ham co san)
if strcmpi(mfilename, 'filter')
    error('Script dang ten filter.m, hay doi ten khac.');
end

%% 1. Cau hinh
folder = 'D:\DSP\';
data_list = {
    'rssi_1m.csv', 1;
    'rssi_2m.csv', 2;
    'rssi_3m.csv', 3;
    'rssi_4m.csv', 4;
    'rssi_5m.csv', 5;
};
EXCLUDE = [];     % khoang cach loai khoi hoi quy, vi du [5]
T_SKIP  = 3;      % giay dau bo di
MED_WIN = 5;      % cua so median (so goi) de bo xung nhon

nF = size(data_list, 1);

%% 2. Doc va xu ly tung file
d_true    = zeros(nF, 1);
rssi_mean = zeros(nF, 1);
rssi_med  = zeros(nF, 1);
rssi_std  = zeros(nF, 1);
pkt_rate  = zeros(nF, 1);
samples   = cell(nF, 1);
t_all     = cell(nF, 1);
x_all     = cell(nF, 1);

for k = 1:nF
    fpath = [folder data_list{k, 1}];
    if exist(fpath, 'file') ~= 2
        error('Khong thay file: %s', fpath);
    end
    T  = readtable(fpath);
    vn = T.Properties.VariableNames;
    if any(strcmp(vn, 'rssi_dbm'))
        x = T.rssi_dbm;
    elseif any(strcmp(vn, 'rssi_raw'))
        x = T.rssi_raw;
    else
        error('Khong thay cot RSSI trong %s', fpath);
    end
    t = T.time_s;
    t = t - t(1);

    xm = movmedian(x, MED_WIN);
    xs = xm(t >= T_SKIP);

    d_true(k)    = data_list{k, 2};
    rssi_mean(k) = mean(xs);
    rssi_med(k)  = median(xs);
    rssi_std(k)  = std(xs);
    pkt_rate(k)  = numel(t) / t(end);
    samples{k}   = xs;
    t_all{k}     = t(:);
    x_all{k}     = double(x(:));
end

%% 3. Bang thong ke
disp(' ');
disp('  d(m)   TB(dBm)  TrungVi   Std(dB)   Goi/s');
for k = 1:nF
    fprintf('%6.2f %9.2f %8.2f %9.2f %7.2f\n', ...
        d_true(k), rssi_mean(k), rssi_med(k), rssi_std(k), pkt_rate(k));
end

%% 4. Hoi quy: RSSI = RSSI_1m - 10*n*log10(d)
use = ~ismember(d_true, EXCLUDE);
if sum(use) < 3
    error('Can it nhat 3 muc khoang cach de hoi quy.');
end
X = log10(d_true(use));
Y = rssi_mean(use);
m = numel(X);

p     = polyfit(X, Y, 1);
n_fit = -p(1) / 10;
A     = p(2);
res   = Y - polyval(p, X);
SSres = sum(res .^ 2);
SStot = sum((Y - mean(Y)) .^ 2);
R2    = 1 - SSres / SStot;

% Sai so chuan va khoang tin cay 95%
s2   = SSres / (m - 2);
Sxx  = sum((X - mean(X)) .^ 2);
se_n = sqrt(s2 / Sxx) / 10;
se_A = sqrt(s2 * (1 / m + mean(X) ^ 2 / Sxx));
tab  = [12.706 4.303 3.182 2.776 2.571 2.447 2.365 2.306 2.262 2.228];
df   = m - 2;
if df <= numel(tab)
    tcrit = tab(df);
else
    tcrit = 1.96;
end

disp(' ');
disp('===== KET QUA HOI QUY =====');
disp(['Cac muc dung de fit (m): ' sprintf('%g ', d_true(use))]);
fprintf('RSSI_1m = %.2f dBm (+- %.2f, 95 phan tram)\n', A, tcrit * se_A);
fprintf('n       = %.2f (+- %.2f, 95 phan tram)\n', n_fit, tcrit * se_n);
fprintf('R^2     = %.3f\n', R2);
fprintf('RMS phan du = %.2f dB\n', sqrt(SSres / m));
disp(['Phan du tung muc (dB): ' sprintf('%.2f ', res)]);
if n_fit < 1 || n_fit > 5
    disp('>> n ngoai khoang hop ly (1 - 5): xem lai du lieu.');
end

%% 5. Leave-one-out: fit bang cac muc con lai, du doan muc bi bo
disp(' ');
disp('===== LEAVE-ONE-OUT =====');
disp('d that   d trung vi   RMSE(m)   Trong 0.5m   Trong 1m');
idx_use = find(use);
for q = 1:numel(idx_use)
    k   = idx_use(q);
    idx = idx_use(idx_use ~= k);
    pk  = polyfit(log10(d_true(idx)), rssi_mean(idx), 1);
    nk  = -pk(1) / 10;
    if nk <= 0.1
        fprintf('%6.2f   (bo qua: n = %.2f)\n', d_true(k), nk);
        continue;
    end
    dh  = 10 .^ ((pk(2) - samples{k}) / (10 * nk));
    err = dh - d_true(k);
    in05 = 100 * mean(abs(err) <= 0.5);
    in10 = 100 * mean(abs(err) <= 1);
    fprintf('%6.2f %11.2f %9.2f %10.0f%% %8.0f%%\n', ...
        d_true(k), median(dh), sqrt(mean(err .^ 2)), in05, in10);
end

%% 6. Do thi
figure('Name', 'Hoi quy RSSI - khoang cach');
subplot(2, 1, 1);
hold on;
for k = 1:nF
    plot(d_true(k) * ones(size(samples{k})), samples{k}, ...
        '.', 'Color', [0.75 0.75 0.75]);
end
errorbar(d_true, rssi_mean, rssi_std, 'o', 'LineWidth', 1.5);
dd = linspace(min(d_true) * 0.8, max(d_true) * 1.2, 100);
plot(dd, polyval(p, log10(dd)), '-', 'LineWidth', 1.5);
set(gca, 'XScale', 'log');
grid on;
xlabel('Khoang cach thuc te (m)');
ylabel('RSSI (dBm)');
title(sprintf('RSSI_1m = %.1f dBm, n = %.2f, R^2 = %.2f', A, n_fit, R2));

subplot(2, 1, 2);
bar(d_true(use), res);
grid on;
xlabel('Khoang cach thuc te (m)');
ylabel('Phan du (dB)');
title('Phan du cua mo hinh (do - fit)');

%% 6b. Spectrum (pho cong suat Welch) cua RSSI tho theo tung khoang cach
fs_u = 2;                  % Hz, tan so lay mau sau noi suy (khop ~2 goi/s)
Lw   = 64;                 % do dai moi doan (mau): 64 mau = 32 s
hop  = Lw / 2;             % chong lap 50 phan tram
w    = 0.5 - 0.5 * cos(2 * pi * (0:Lw - 1)' / (Lw - 1));
U    = sum(w .^ 2);
nh   = Lw / 2 + 1;
f    = (0:nh - 1)' * fs_u / Lw;

figure('Name', 'Spectrum RSSI');
hold on;
for k = 1:nF
    tt = t_all{k};
    xx = x_all{k};
    [tt, iu] = unique(tt);
    xx = xx(iu);
    tu = (tt(1):1 / fs_u:tt(end))';
    xu = interp1(tt, xx, tu, 'previous', 'extrap');
    N  = numel(xu);
    nseg = floor((N - Lw) / hop) + 1;
    if nseg < 1
        fprintf('Bo qua spectrum %.1f m: it hon %d mau\n', d_true(k), Lw);
        continue;
    end
    Pxx = zeros(nh, 1);
    for sg = 1:nseg
        seg = xu((sg - 1) * hop + (1:Lw));
        seg = (seg - mean(seg)) .* w;
        Xf  = fft(seg);
        P1  = (abs(Xf(1:nh)) .^ 2) / (fs_u * U);
        P1(2:end - 1) = 2 * P1(2:end - 1);
        Pxx = Pxx + P1;
    end
    Pxx = Pxx / nseg;
    plot(f, 10 * log10(Pxx + eps), 'LineWidth', 1.3, ...
        'DisplayName', sprintf('%.1f m', d_true(k)));
end
grid on;
xlabel('Tan so (Hz)');
ylabel('Mat do cong suat (dB/Hz)');
title('Spectrum RSSI theo khoang cach (Welch, fs = 2 Hz)');
legend('Location', 'northeast');

%% 7. Hang so de dua sang Python
disp(' ');
disp('Dua vao script Python:');
fprintf('RSSI_1M = %.2f\n', A);
fprintf('N_FACTOR = %.2f\n', n_fit);

%% 8. Vi du: doi RSSI sang khoang cach
rssi_test = -70;
d_test = 10 ^ ((A - rssi_test) / (10 * n_fit));
fprintf('Vi du: RSSI = %d dBm -> d = %.2f m\n', rssi_test, d_test);