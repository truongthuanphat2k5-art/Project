clear; clc; close all;

%% Cau hinh
folder   = 'D:\DSP\';
rx_file  = {'maya', 'mayb'};      % ten file: rssi_<rx>_<d>m.csv
rx_name  = {'MayA', 'MayB'};      % ten may thu trong script Python
rx_label = {'d_A', 'd_B'};
d = [1 2 3 4];                  % khoang cach thuc te (m)

fs_u = 3;         % Hz, tan so lay mau sau noi suy (khop ~3.3 goi/s)
Lw   = 64;        % do dai moi doan Welch (mau)
hop  = Lw / 2;    % chong lap 50 phan tram

nR = numel(rx_name);
nD = numel(d);
t_all = cell(nR, nD);
x_all = cell(nR, nD);
m_all = zeros(nR, nD);
s_all = zeros(nR, nD);

%% 1. Doc du lieu (cot time_s, rssi_dbm)
for a = 1:nR
    for k = 1:nD
        fpath = sprintf('%srssi_%s_%dm.csv', folder, rx_file{a}, d(k));
        if exist(fpath, 'file') ~= 2
            error('Khong thay file: %s', fpath);
        end
        T = readtable(fpath);
        t = T.time_s(:);
        x = double(T.rssi_dbm(:));
        t_all{a, k} = t - t(1);
        x_all{a, k} = x;
        m_all(a, k) = mean(x);
        s_all(a, k) = std(x);
    end
end

for a = 1:nR
    disp(' ');
    fprintf('===== %s =====\n', rx_name{a});
    disp('  d(m)   So mau   TB(dBm)   Std(dB)   Goi/s');
    for k = 1:nD
        n_s = numel(x_all{a, k});
        rate = n_s / t_all{a, k}(end);
        fprintf('%6.1f %8d %9.2f %9.2f %7.2f\n', d(k), n_s, m_all(a, k), s_all(a, k), rate);
    end
end

%% 2. He so cong thuc khoang cach: RSSI = RSSI_1M - 10*n*log10(d)
tab = [12.706 4.303 3.182 2.776 2.571 2.447 2.365 2.306 2.262 2.228];
X   = log10(d(:));
A_fit = zeros(1, nR);
n_fit = zeros(1, nR);
R2    = zeros(1, nR);
fit_p = zeros(nR, 2);

for a = 1:nR
    Y = m_all(a, :)';
    p = polyfit(X, Y, 1);
    fit_p(a, :) = p;
    n_fit(a) = -p(1) / 10;
    A_fit(a) = p(2);
    res   = Y - polyval(p, X);
    SSres = sum(res .^ 2);
    SStot = sum((Y - mean(Y)) .^ 2);
    R2(a) = 1 - SSres / SStot;

    s2   = SSres / (nD - 2);
    Sxx  = sum((X - mean(X)) .^ 2);
    se_n = sqrt(s2 / Sxx) / 10;
    se_A = sqrt(s2 * (1 / nD + mean(X) ^ 2 / Sxx));
    df   = nD - 2;
    if df <= numel(tab)
        tcrit = tab(df);
    else
        tcrit = 1.96;
    end

    disp(' ');
    fprintf('===== HOI QUY %s =====\n', rx_name{a});
    fprintf('RSSI_1M  = %.2f dBm (+- %.2f, 95 phan tram)\n', A_fit(a), tcrit * se_A);
    fprintf('N_FACTOR = %.2f (+- %.2f, 95 phan tram)\n', n_fit(a), tcrit * se_n);
    fprintf('R^2 = %.3f, RMS phan du = %.2f dB\n', R2(a), sqrt(SSres / nD));
    disp(['Phan du tung muc (dB): ' sprintf('%.2f ', res)]);
end

%% 3. Do thi hoi quy RSSI theo khoang cach
figure('Name', 'Hoi quy RSSI - khoang cach');
cols = {'b', 'r'};
hold on;
dd = linspace(min(d) * 0.8, max(d) * 1.2, 100);
for a = 1:nR
    errorbar(d, m_all(a, :), s_all(a, :), [cols{a} 'o'], 'LineWidth', 1.5);
    plot(dd, polyval(fit_p(a, :), log10(dd)), cols{a}, 'LineWidth', 1.3);
end
set(gca, 'XScale', 'log');
grid on;
xlabel('Khoang cach thuc te (m)');
ylabel('RSSI (dBm)');
legend('MayA (do)', 'MayA (fit)', 'MayB (do)', 'MayB (fit)', 'Location', 'southwest');
title('RSSI theo khoang cach cua realme8 tai MayA va MayB');

%% 4. Bieu do pho (Welch) cua RSSI tho theo khoang cach
w  = 0.5 - 0.5 * cos(2 * pi * (0:Lw - 1)' / (Lw - 1));
U  = sum(w .^ 2);
nh = Lw / 2 + 1;
f  = (0:nh - 1)' * fs_u / Lw;

figure('Name', 'Pho RSSI');
for a = 1:nR
    subplot(nR, 1, a);
    hold on;
    for k = 1:nD
        tt = t_all{a, k};
        xx = x_all{a, k};
        [tt, iu] = unique(tt);
        xx = xx(iu);
        tu = (tt(1):1 / fs_u:tt(end))';
        xu = interp1(tt, xx, tu, 'previous', 'extrap');
        N  = numel(xu);
        nseg = floor((N - Lw) / hop) + 1;
        if nseg < 1
            fprintf('Bo qua pho %s %d m: it hon %d mau\n', rx_name{a}, d(k), Lw);
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
        plot(f, 10 * log10(Pxx + eps), 'LineWidth', 1.2, ...
            'DisplayName', sprintf('%d m', d(k)));
    end
    grid on;
    xlabel('Tan so (Hz)');
    ylabel('PSD (dB/Hz)');
    title(sprintf('Pho RSSI tai %s (Welch, fs = %g Hz)', rx_name{a}, fs_u));
    legend('Location', 'northeast');
end

%% 5. He so de dua vao script Python
disp(' ');
disp('Dua vao script Python:');
for a = 1:nR
    fprintf('    "%s": {"label": "%s", "RSSI_1M": %.2f, "N_FACTOR": %.2f},\n', ...
        rx_name{a}, rx_label{a}, A_fit(a), n_fit(a));
end